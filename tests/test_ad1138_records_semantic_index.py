"""AD-1138: semantic index over Ship's Records (Σ discoverable), Oracle Tier 2.

Real fixtures per BF-287 — a real ``RecordsStore`` and a real
``SemanticKnowledgeLayer`` on ``tmp_path``. Nothing here mocks ChromaDB, so the
classification ``where`` clauses are exercised against the installed engine.

DD-6: CI forces ``PROBOS_EMBEDDINGS=local`` (BF-657), where the embedding
function is lexical rather than semantic. Tests asserting *semantic* quality
skip in that mode; every structural test (indexing, classification filtering,
fallback) runs in both.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.oracle_service import OracleService, _decode_record_frontmatter
from probos.config import RecordsConfig
from probos.knowledge.records_store import RecordsStore
from probos.knowledge.semantic import (
    SemanticKnowledgeLayer,
    build_records_scope_filter,
)

_ALL_CLASSIFICATIONS = ("private", "department", "ship", "fleet")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _real_embeddings_available() -> bool:
    """DD-6: True only when a genuinely semantic embedding model is loaded."""
    from probos.knowledge.embeddings import get_embedding_function

    return get_embedding_function() is not None


@pytest.fixture
async def records(tmp_path: Path) -> RecordsStore:
    cfg = RecordsConfig(
        repo_path=str(tmp_path / "ship-records"),
        auto_commit=False,
    )
    store = RecordsStore(cfg)
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


class _RecordingCollection:
    """Pass-through wrapper that records the kwargs handed to ``query``."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.queries: list[dict[str, Any]] = []

    def count(self) -> int:
        return self._inner.count()

    def upsert(self, **kwargs: Any) -> Any:
        return self._inner.upsert(**kwargs)

    def query(self, **kwargs: Any) -> Any:
        self.queries.append(kwargs)
        return self._inner.query(**kwargs)


async def _seed_four_levels(store: RecordsStore) -> None:
    """One real record per classification, all sharing the token 'reactor'."""
    await store.write_entry(
        author="alice", path="reports/private-note.md",
        content="reactor coolant readings alice keeps to herself",
        message="private", classification="private", department="engineering",
    )
    await store.write_entry(
        author="bob", path="reports/dept-note.md",
        content="reactor maintenance schedule for the engineering department",
        message="department", classification="department", department="engineering",
    )
    await store.write_entry(
        author="carol", path="reports/ship-note.md",
        content="reactor status briefing for the whole ship",
        message="ship", classification="ship",
    )
    await store.write_entry(
        author="dave", path="reports/fleet-note.md",
        content="reactor doctrine shared across the fleet",
        message="fleet", classification="fleet",
    )


def _classifications(rows: list[dict]) -> set[str]:
    return {(r.get("metadata") or {}).get("classification", "") for r in rows}


def _paths(rows: list[dict]) -> set[str]:
    return {(r.get("metadata") or {}).get("path", "") for r in rows}


def _make_oracle(
    *,
    records_store: Any = None,
    semantic_layer: Any = None,
    enabled: bool = False,
) -> OracleService:
    return OracleService(
        records_store=records_store,
        semantic_layer=semantic_layer,
        records_semantic_enabled=enabled,
    )


# ---------------------------------------------------------------------------
# DD-1 — collection registration + AD-584 migration inheritance
# ---------------------------------------------------------------------------

class TestCollectionRegistration:
    def test_records_collection_is_registered(self) -> None:
        assert SemanticKnowledgeLayer.COLLECTIONS["records"] == "sk_records"

    async def test_started_layer_reports_records_collection(self, layer) -> None:
        assert layer.stats()["records"] == 0

    async def test_records_collection_inherits_ad584_migration(self, layer) -> None:
        """DD-1 asked this be verified rather than assumed.

        ``_migrate_collections_if_needed`` iterates ``COLLECTIONS``, so the new
        entry should be delete+recreated on an embedding-model change like any
        other. Proven by indexing a document and watching it clear.
        """
        from probos.knowledge.embeddings import get_collection_embedding_function

        await layer.index_record(path="reports/a.md", content="warp core alignment")
        assert layer.stats()["records"] == 1

        layer._migrate_collections_if_needed(
            "ad1138-different-model", get_collection_embedding_function(),
        )

        assert layer.stats()["records"] == 0
        recreated = layer._collections["records"]
        assert recreated.metadata.get("embedding_model") == "ad1138-different-model"


# ---------------------------------------------------------------------------
# DD-2 — the scope filter itself (pure)
# ---------------------------------------------------------------------------

class TestScopeFilterShape:
    def test_ship_scope_permits_levels_at_or_below(self) -> None:
        where = build_records_scope_filter("ship")
        permitted = set(where["classification"]["$in"])
        assert permitted == {"private", "department", "ship"}
        assert "fleet" not in permitted

    def test_fleet_scope_permits_every_classification(self) -> None:
        where = build_records_scope_filter("fleet")
        assert set(where["classification"]["$in"]) == set(_ALL_CLASSIFICATIONS)

    def test_private_scope_permits_only_private(self) -> None:
        where = build_records_scope_filter("private")
        assert where["classification"]["$in"] == ["private"]

    def test_unknown_scope_defaults_to_ship(self) -> None:
        assert build_records_scope_filter("nonsense") == build_records_scope_filter("ship")

    def test_single_predicate_stays_flat(self) -> None:
        """ChromaDB 1.5.8 rejects a flat multi-key where AND a 1-element $and."""
        where = build_records_scope_filter("ship")
        assert set(where.keys()) == {"classification"}

    def test_reader_identity_gates_private_and_department(self) -> None:
        where = build_records_scope_filter("ship", reader_id="alice")
        clauses = where["$or"]
        assert {"classification": {"$in": ["ship"]}} in clauses
        assert {"$and": [
            {"classification": {"$in": ["private", "department"]}},
            {"author": "alice"},
        ]} in clauses
        # No department supplied ⇒ no same-department clause.
        assert len(clauses) == 2

    def test_reader_department_adds_same_department_clause(self) -> None:
        where = build_records_scope_filter(
            "ship", reader_id="alice", reader_department="engineering",
        )
        clauses = where["$or"]
        assert len(clauses) == 3
        assert {"$and": [
            {"classification": "department"},
            {"department": "engineering"},
        ]} in clauses

    def test_captain_skips_the_identity_gate(self) -> None:
        assert build_records_scope_filter(
            "ship", reader_id="captain", reader_department="command",
        ) == build_records_scope_filter("ship")

    def test_never_emits_a_single_element_and_or(self) -> None:
        """ChromaDB requires $and/$or to hold at least two expressions."""

        def _assert_valid(node: Any) -> None:
            if not isinstance(node, dict):
                return
            for key, value in node.items():
                if key in ("$and", "$or"):
                    assert isinstance(value, list) and len(value) >= 2, (
                        f"{key} must hold >= 2 expressions, got {value!r}"
                    )
                    for child in value:
                        _assert_valid(child)
                else:
                    _assert_valid(value)

        for scope in (*_ALL_CLASSIFICATIONS, "unknown"):
            for reader_id in ("", "captain", "alice"):
                for dept in ("", "engineering"):
                    where = build_records_scope_filter(
                        scope, reader_id=reader_id, reader_department=dept,
                    )
                    if where is not None:
                        _assert_valid(where)


# ---------------------------------------------------------------------------
# DD-2 — enforcement against real ChromaDB with real records (LOAD-BEARING)
# ---------------------------------------------------------------------------

class TestClassificationEnforcement:
    async def test_ship_scope_excludes_fleet_record(self, records, layer) -> None:
        records.set_semantic_indexer(layer)
        await _seed_four_levels(records)

        rows = await layer.search("reactor", types=["records"], records_scope="ship")

        assert _classifications(rows) == {"private", "department", "ship"}
        assert "reports/fleet-note.md" not in _paths(rows)

    async def test_semantic_admits_same_classifications_as_keyword(
        self, records, layer,
    ) -> None:
        """DD-2's actual requirement: not a bypass around records_store.search.

        Both paths run at the scope Tier 2 uses, over the same four real
        records, and must admit exactly the same classification set.
        """
        records.set_semantic_indexer(layer)
        await _seed_four_levels(records)

        keyword = await records.search("reactor", scope="ship")
        keyword_classes = {
            r["frontmatter"].get("classification", "") for r in keyword
        }
        semantic = await layer.search(
            "reactor", types=["records"], limit=20, records_scope="ship",
        )

        assert keyword_classes == _classifications(semantic)

    async def test_private_record_hidden_from_another_reader(
        self, records, layer,
    ) -> None:
        records.set_semantic_indexer(layer)
        await _seed_four_levels(records)

        as_bob = await layer.search(
            "reactor", types=["records"], limit=20,
            records_scope="ship", reader_id="bob",
        )
        assert "reports/private-note.md" not in _paths(as_bob)

        as_alice = await layer.search(
            "reactor", types=["records"], limit=20,
            records_scope="ship", reader_id="alice",
        )
        assert "reports/private-note.md" in _paths(as_alice)

    async def test_department_record_hidden_cross_department(
        self, records, layer,
    ) -> None:
        records.set_semantic_indexer(layer)
        await _seed_four_levels(records)

        outsider = await layer.search(
            "reactor", types=["records"], limit=20, records_scope="ship",
            reader_id="erin", reader_department="medical",
        )
        assert "reports/dept-note.md" not in _paths(outsider)

        insider = await layer.search(
            "reactor", types=["records"], limit=20, records_scope="ship",
            reader_id="erin", reader_department="engineering",
        )
        assert "reports/dept-note.md" in _paths(insider)

        author = await layer.search(
            "reactor", types=["records"], limit=20, records_scope="ship",
            reader_id="bob", reader_department="medical",
        )
        assert "reports/dept-note.md" in _paths(author)

    async def test_scope_is_a_where_clause_not_a_post_filter(
        self, records, layer,
    ) -> None:
        records.set_semantic_indexer(layer)
        await _seed_four_levels(records)
        recorder = _RecordingCollection(layer._collections["records"])
        layer._collections["records"] = recorder

        await layer.search("reactor", types=["records"], records_scope="ship")

        assert len(recorder.queries) == 1
        assert recorder.queries[0]["where"] == build_records_scope_filter("ship")

    async def test_other_collections_receive_no_where_clause(self, layer) -> None:
        """Byte-identity guard: the filter is records-only."""
        await layer.index_event(category="ops", event="boot", detail="ready")
        recorder = _RecordingCollection(layer._collections["events"])
        layer._collections["events"] = recorder

        await layer.search("boot", types=["events"], records_scope="ship")

        assert len(recorder.queries) == 1
        assert "where" not in recorder.queries[0]


# ---------------------------------------------------------------------------
# search() gating — records fail closed
# ---------------------------------------------------------------------------

class TestRecordsFailClosed:
    async def test_records_excluded_when_no_scope_given(self, records, layer) -> None:
        """Protects every pre-AD-1138 caller (notably Oracle Tier 5)."""
        records.set_semantic_indexer(layer)
        await _seed_four_levels(records)

        rows = await layer.search("reactor", limit=20)

        assert not any(r["type"] == "record" for r in rows)

    async def test_records_excluded_when_typed_but_unscoped(
        self, records, layer,
    ) -> None:
        records.set_semantic_indexer(layer)
        await _seed_four_levels(records)

        assert await layer.search("reactor", types=["records"], limit=20) == []

    async def test_records_returned_when_scope_given(self, records, layer) -> None:
        records.set_semantic_indexer(layer)
        await _seed_four_levels(records)

        rows = await layer.search(
            "reactor", types=["records"], limit=20, records_scope="fleet",
        )

        assert len(rows) == 4


# ---------------------------------------------------------------------------
# index_record
# ---------------------------------------------------------------------------

class TestIndexRecord:
    async def test_unknown_classification_normalizes_to_private(self, layer) -> None:
        await layer.index_record(
            path="reports/odd.md", content="warp field harmonics",
            classification="top-secret",
        )

        as_ship = await layer.search(
            "warp", types=["records"], records_scope="ship",
        )
        assert _classifications(as_ship) == {"private"}

    async def test_rewriting_a_record_upserts_in_place(self, layer) -> None:
        await layer.index_record(path="reports/a.md", content="first revision")
        await layer.index_record(path="reports/a.md", content="second revision")

        assert layer.stats()["records"] == 1

    async def test_index_record_without_started_layer_is_a_noop(self, tmp_path) -> None:
        sk = SemanticKnowledgeLayer(db_path=tmp_path / "unstarted")

        await sk.index_record(path="reports/a.md", content="body")  # must not raise

    async def test_unserialisable_frontmatter_degrades_to_empty(self, layer) -> None:
        """``default=str`` absorbs exotic values, but not a cycle."""
        cyclic: dict[str, Any] = {"author": "carol"}
        cyclic["self"] = cyclic

        await layer.index_record(
            path="reports/a.md", content="plasma conduit", frontmatter=cyclic,
        )

        rows = await layer.search(
            "plasma", types=["records"], records_scope="ship",
        )
        assert rows[0]["metadata"]["frontmatter_json"] == "{}"

    async def test_oversized_frontmatter_degrades_to_empty(self, layer) -> None:
        await layer.index_record(
            path="reports/b.md", content="plasma conduit",
            frontmatter={"notes": "x" * 8000},
        )

        rows = await layer.search(
            "plasma", types=["records"], records_scope="ship",
        )
        assert rows[0]["metadata"]["frontmatter_json"] == "{}"

    async def test_ordinary_frontmatter_is_preserved(self, layer) -> None:
        await layer.index_record(
            path="reports/c.md", content="plasma conduit",
            frontmatter={"author": "carol", "tags": ["safety"]},
        )

        rows = await layer.search(
            "plasma", types=["records"], records_scope="ship",
        )
        assert _decode_record_frontmatter(
            rows[0]["metadata"]["frontmatter_json"],
        ) == {"author": "carol", "tags": ["safety"]}

    async def test_tags_and_topic_enrich_the_indexed_document(self, layer) -> None:
        await layer.index_record(
            path="reports/a.md", content="body text",
            topic="containment", tags=["safety", "drill"],
        )

        rows = await layer.search("body", types=["records"], records_scope="ship")
        assert "containment" in rows[0]["document"]
        assert "safety" in rows[0]["document"]


# ---------------------------------------------------------------------------
# DD-3 / DD-4 — Oracle Tier 2
# ---------------------------------------------------------------------------

class TestOracleTier2:
    async def test_default_off_uses_keyword_path(self, records, layer) -> None:
        records.set_semantic_indexer(layer)
        await _seed_four_levels(records)
        recorder = _RecordingCollection(layer._collections["records"])
        layer._collections["records"] = recorder
        oracle = _make_oracle(records_store=records, semantic_layer=layer)

        results = await oracle._query_records("reactor", k=5)
        expected = await oracle._query_records_keyword("reactor", k=5)

        assert recorder.queries == []
        assert [(r.source_tier, r.content, r.score, r.metadata, r.provenance)
                for r in results] == [
            (r.source_tier, r.content, r.score, r.metadata, r.provenance)
            for r in expected
        ]

    async def test_semantic_path_keeps_the_tier2_result_shape(
        self, records, layer,
    ) -> None:
        records.set_semantic_indexer(layer)
        await _seed_four_levels(records)
        oracle = _make_oracle(
            records_store=records, semantic_layer=layer, enabled=True,
        )

        results = await oracle._query_records("reactor", k=5)

        assert results
        for r in results:
            assert r.source_tier == "records"
            assert r.provenance == "[ship's records]"
            assert set(r.metadata) == {"path", "frontmatter"}
            assert isinstance(r.metadata["frontmatter"], dict)
            assert 0.0 <= r.score <= 1.0

    async def test_semantic_path_recovers_frontmatter(self, records, layer) -> None:
        records.set_semantic_indexer(layer)
        await records.write_entry(
            author="carol", path="reports/ship-note.md",
            content="reactor status briefing", message="ship",
            classification="ship", topic="reactor",
        )
        oracle = _make_oracle(
            records_store=records, semantic_layer=layer, enabled=True,
        )

        results = await oracle._query_records("reactor", k=5)

        assert results[0].metadata["path"] == "reports/ship-note.md"
        assert results[0].metadata["frontmatter"]["author"] == "carol"
        assert results[0].metadata["frontmatter"]["classification"] == "ship"

    async def test_semantic_path_excludes_fleet_records(self, records, layer) -> None:
        records.set_semantic_indexer(layer)
        await _seed_four_levels(records)
        oracle = _make_oracle(
            records_store=records, semantic_layer=layer, enabled=True,
        )

        results = await oracle._query_records("reactor", k=10)

        assert "reports/fleet-note.md" not in {r.metadata["path"] for r in results}

    async def test_falls_back_to_keyword_when_layer_unattached(
        self, records,
    ) -> None:
        await _seed_four_levels(records)
        oracle = _make_oracle(
            records_store=records, semantic_layer=None, enabled=True,
        )

        results = await oracle._query_records("reactor", k=5)

        assert results
        assert all(r.source_tier == "records" for r in results)

    async def test_falls_back_to_keyword_when_collection_empty(
        self, records, layer,
    ) -> None:
        await _seed_four_levels(records)  # written with NO indexer attached
        oracle = _make_oracle(
            records_store=records, semantic_layer=layer, enabled=True,
        )

        assert layer.stats()["records"] == 0
        results = await oracle._query_records("reactor", k=5)

        assert results
        assert "reports/ship-note.md" in {r.metadata["path"] for r in results}

    async def test_falls_back_to_keyword_when_semantic_raises(
        self, records, layer,
    ) -> None:
        records.set_semantic_indexer(layer)
        await _seed_four_levels(records)

        class _Exploding:
            async def search(self, *a: Any, **kw: Any) -> list[dict]:
                raise RuntimeError("chroma down")

        oracle = _make_oracle(
            records_store=records, semantic_layer=_Exploding(), enabled=True,
        )

        results = await oracle._query_records("reactor", k=5)

        assert results
        assert all(r.source_tier == "records" for r in results)

    async def test_semantic_path_opts_out_of_episodes(self, records) -> None:
        """BF-675 interop — Tier 2 must not re-open the episode path either."""
        captured: dict[str, Any] = {}

        class _Layer:
            async def search(self, query: str, **kwargs: Any) -> list[dict]:
                captured.update(kwargs)
                return [{
                    "type": "record", "id": "record_a", "document": "d",
                    "score": 0.9,
                    "metadata": {"path": "reports/a.md", "frontmatter_json": "{}"},
                }]

        oracle = _make_oracle(
            records_store=records, semantic_layer=_Layer(), enabled=True,
        )

        await oracle._query_records("reactor", k=3)

        assert captured["include_episodes"] is False
        assert captured["types"] == ["records"]
        assert captured["records_scope"] == "ship"

    async def test_tier5_still_excludes_episodes_and_records(
        self, records, layer,
    ) -> None:
        """BF-675 + AD-1138: Tier 5 sees neither episodes nor records."""
        records.set_semantic_indexer(layer)
        await _seed_four_levels(records)
        await layer.index_agent(
            agent_type="ReactorAgent", intent_name="reactor_status",
            description="reactor telemetry", strategy="direct",
        )
        oracle = _make_oracle(semantic_layer=layer)

        results = await oracle._query_semantic("reactor", k=10)

        assert results
        assert all(r.source_tier == "semantic" for r in results)
        assert all(r.metadata.get("type") != "record" for r in results)


class TestFrontmatterDecoder:
    @pytest.mark.parametrize("raw", ["", "   ", None, 42, "not json", "[1, 2]", '"str"'])
    def test_degrades_to_empty_dict(self, raw: Any) -> None:
        assert _decode_record_frontmatter(raw) == {}

    def test_round_trips_a_dict(self) -> None:
        assert _decode_record_frontmatter('{"author": "carol"}') == {"author": "carol"}


# ---------------------------------------------------------------------------
# Index-on-write + DD-5 backfill
# ---------------------------------------------------------------------------

class TestWriteThroughAndBackfill:
    async def test_write_entry_indexes_through_the_attached_indexer(
        self, records, layer,
    ) -> None:
        records.set_semantic_indexer(layer)

        await records.write_entry(
            author="carol", path="reports/ship-note.md",
            content="reactor status briefing", message="ship",
            classification="ship",
        )

        assert layer.stats()["records"] == 1

    async def test_write_entry_without_an_indexer_indexes_nothing(
        self, records, layer,
    ) -> None:
        """DD-4 byte-identity: the default None hook leaves write_entry alone."""
        await records.write_entry(
            author="carol", path="reports/ship-note.md",
            content="reactor status briefing", message="ship",
        )

        assert layer.stats()["records"] == 0
        assert (records.repo_path / "reports/ship-note.md").exists()

    async def test_write_entry_survives_an_indexer_failure(self, records) -> None:
        class _Exploding:
            async def index_record(self, **kwargs: Any) -> None:
                raise RuntimeError("chroma down")

        records.set_semantic_indexer(_Exploding())

        path = await records.write_entry(
            author="carol", path="reports/ship-note.md",
            content="reactor status briefing", message="ship",
        )

        assert path == "reports/ship-note.md"
        assert (records.repo_path / path).exists()

    async def test_backfill_indexes_preexisting_records(
        self, records, layer,
    ) -> None:
        await _seed_four_levels(records)  # written before any indexer existed
        assert layer.stats()["records"] == 0

        indexed = await layer.reindex_records(records)

        assert indexed == 4
        assert layer.stats()["records"] == 4
        rows = await layer.search(
            "reactor", types=["records"], limit=20, records_scope="fleet",
        )
        assert _classifications(rows) == set(_ALL_CLASSIFICATIONS)

    async def test_backfill_preserves_classification_metadata(
        self, records, layer,
    ) -> None:
        await _seed_four_levels(records)

        await layer.reindex_records(records)

        rows = await layer.search(
            "reactor", types=["records"], limit=20, records_scope="ship",
        )
        assert "reports/fleet-note.md" not in _paths(rows)

    async def test_backfill_respects_the_limit(self, records, layer) -> None:
        await _seed_four_levels(records)

        indexed = await layer.reindex_records(records, limit=2)

        assert indexed == 2
        assert layer.stats()["records"] == 2

    async def test_backfill_degrades_when_the_store_raises(self, layer) -> None:
        class _Exploding:
            async def list_entries(self, **kwargs: Any) -> list[dict]:
                raise RuntimeError("repo unreadable")

        assert await layer.reindex_records(_Exploding()) == 0

    async def test_backfill_skips_an_unreadable_entry(self, records, layer) -> None:
        await _seed_four_levels(records)
        real_read = records.read_entry

        async def _flaky(path: str, reader_id: str, reader_department: str = ""):
            if path == "reports/ship-note.md":
                raise OSError("disk error")
            return await real_read(path, reader_id, reader_department)

        records.read_entry = _flaky  # type: ignore[method-assign]

        indexed = await layer.reindex_records(records)

        assert indexed == 3
        assert layer.stats()["records"] == 3

    async def test_backfill_without_a_started_layer_returns_zero(
        self, records, tmp_path,
    ) -> None:
        sk = SemanticKnowledgeLayer(db_path=tmp_path / "unstarted")

        assert await sk.reindex_records(records) == 0


# ---------------------------------------------------------------------------
# DD-6 — semantic quality (real embeddings only)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _real_embeddings_available(),
    reason="DD-6: PROBOS_EMBEDDINGS=local uses a lexical EF; no synonym matching",
)
class TestSemanticQuality:
    async def test_record_retrievable_without_lexical_overlap(
        self, records, layer,
    ) -> None:
        records.set_semantic_indexer(layer)
        await records.write_entry(
            author="carol", path="reports/rollback.md",
            content=(
                "Deployment rollback lessons: when a release introduces a "
                "regression, restore the previous build immediately."
            ),
            message="lessons", classification="ship",
        )
        await records.write_entry(
            author="carol", path="reports/galley.md",
            content="Galley inventory: replicator ration packs and beverages.",
            message="galley", classification="ship",
        )

        rows = await layer.search(
            "how do we revert a bad release",
            types=["records"], limit=5, records_scope="ship",
        )

        assert rows
        assert rows[0]["metadata"]["path"] == "reports/rollback.md"
