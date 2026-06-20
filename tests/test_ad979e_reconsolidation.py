"""AD-979e slice 1 (#907): self-healing reconsolidation — capture/persist an
additive, capped, provenance-tagged recall access path.

Slice 1 is deliberately conservative: additive metadata-only, DIRECT-only,
capped, provenance-tagged, default-OFF, capture-only with NO recall read and NO
content mutation. These tests prove:
  * default-OFF is byte-identical (no metadata written, canonical content intact);
  * an ON write is additive-only (only ``reconsol_access_paths_json`` changes —
    ``user_input``/``reflection``/``timestamp``/``importance``/document identical);
  * the AD-541b write-once invariant survives (a second ``store()`` is still
    skipped, and it routed through metadata-only ``update_episode_metadata``);
  * the per-episode FIFO cap, repeat-poison de-dup, DIRECT-only whitelist,
    provenance envelope, and honest-degrade gates behave as specified.

BF-287 discipline: a REAL ``EpisodicMemory`` on ``tmp_path`` with real ONNX
MiniLM embeddings (NOT MagicMock) and a real ``Episode(source="direct")``.
Metadata and documents are read back through the real ChromaDB collection.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from probos.cognitive.episodic import (
    EpisodicMemory,
    _RECONSOL_MAX_PATHS,
    _normalize_access_terms,
)
from probos.types import Episode, MemorySource


@pytest.fixture
async def make_memory(tmp_path: Path):
    """Factory for REAL EpisodicMemory instances (auto-stopped at teardown)."""
    created: list[EpisodicMemory] = []

    async def _make(*, enabled: bool) -> EpisodicMemory:
        em = EpisodicMemory(
            db_path=str(tmp_path / f"ad979e_{len(created)}.db"),
            reconsolidation_enabled=enabled,
        )
        await em.start()
        created.append(em)
        return em

    yield _make
    for em in created:
        try:
            await em.stop()
        except Exception:
            pass


def _meta(em: EpisodicMemory, ep_id: str) -> dict:
    res = em._collection.get(ids=[ep_id], include=["metadatas"])
    metas = res.get("metadatas") or []
    return dict(metas[0]) if metas else {}


def _doc(em: EpisodicMemory, ep_id: str) -> str:
    res = em._collection.get(ids=[ep_id], include=["documents"])
    docs = res.get("documents") or []
    return docs[0] if docs else ""


def _paths(em: EpisodicMemory, ep_id: str) -> list[dict]:
    raw = _meta(em, ep_id).get("reconsol_access_paths_json", "")
    return json.loads(raw) if raw else []


# ============================ 1. default-OFF ============================


@pytest.mark.asyncio
async def test_default_off_is_byte_identical(make_memory):
    # Flag OFF (default) -> record returns False, NO metadata key is added, and
    # the canonical user_input is untouched (byte-identical).
    em = await make_memory(enabled=False)
    ep = Episode(user_input="the warp core breach drill on deck seven", source="direct")
    await em.store(ep)
    user_input_before = _meta(em, ep.id).get("user_input")

    ok = await em.record_recall_access_path(
        ep.id, query="deck seven incident", bridge="test"
    )

    assert ok is False
    meta = _meta(em, ep.id)
    assert "reconsol_access_paths_json" not in meta
    assert meta.get("user_input") == user_input_before


# ============================ 2. ON additive write ============================


@pytest.mark.asyncio
async def test_on_additive_write_records_one_path(make_memory):
    em = await make_memory(enabled=True)
    ep = Episode(user_input="the warp core breach drill", source="direct")
    await em.store(ep)

    ok = await em.record_recall_access_path(
        ep.id, query="reactor containment failure", bridge="cross_agent"
    )

    assert ok is True
    paths = _paths(em, ep.id)
    assert len(paths) == 1
    entry = paths[0]
    assert set(entry.keys()) == {"q", "bridge", "ts", "src"}
    assert entry["bridge"] == "cross_agent"
    assert entry["src"] == MemorySource.DIRECT.value
    assert isinstance(entry["ts"], (int, float))
    assert entry["q"] == sorted(_normalize_access_terms("reactor containment failure"))


# ============================ 3. additive-only invariant ============================


@pytest.mark.asyncio
async def test_additive_only_canonical_content_untouched(make_memory):
    em = await make_memory(enabled=True)
    ep = Episode(
        user_input="original captain's order",
        reflection="my private reflection",
        importance=7,
        timestamp=1234567.5,
        source="direct",
    )
    await em.store(ep)
    meta_before = _meta(em, ep.id)
    doc_before = _doc(em, ep.id)
    assert "reconsol_access_paths_json" not in meta_before

    ok = await em.record_recall_access_path(
        ep.id, query="what was the order", bridge="recall"
    )
    assert ok is True

    meta_after = _meta(em, ep.id)
    doc_after = _doc(em, ep.id)
    # Exactly one key added; nothing removed; the document is byte-identical.
    assert set(meta_after) == set(meta_before) | {"reconsol_access_paths_json"}
    assert doc_after == doc_before
    # Every canonical field is identical pre/post.
    for key in ("user_input", "reflection", "timestamp", "importance", "content_hash", "source"):
        assert meta_after[key] == meta_before[key], key


# ============================ 4. AD-541b write-once intact ============================


@pytest.mark.asyncio
async def test_ad541b_write_once_survives_path_write(make_memory):
    em = await make_memory(enabled=True)
    ep = Episode(user_input="immutable original", source="direct")
    await em.store(ep)

    ok = await em.record_recall_access_path(
        ep.id, query="immutable lookup", bridge="recall"
    )
    assert ok is True
    assert len(_paths(em, ep.id)) == 1

    # A second store() of the same id is still skipped (write-once); it must NOT
    # overwrite content nor clear the metadata-only path write.
    tampered = Episode(id=ep.id, user_input="TAMPERED CONTENT", source="direct")
    await em.store(tampered)

    meta = _meta(em, ep.id)
    assert meta["user_input"] == "immutable original"
    assert len(_paths(em, ep.id)) == 1


# ============================ 5. per-episode FIFO cap ============================


@pytest.mark.asyncio
async def test_per_episode_cap_fifo_evicts_oldest(make_memory):
    em = await make_memory(enabled=True)
    ep = Episode(user_input="hot episode", source="direct")
    await em.store(ep)

    n = _RECONSOL_MAX_PATHS + 3  # distinct queries beyond the cap
    for i in range(1, n + 1):
        ok = await em.record_recall_access_path(
            ep.id, query=f"recall token{i:02d} via bridge", bridge="recall"
        )
        assert ok is True

    paths = _paths(em, ep.id)
    assert len(paths) == _RECONSOL_MAX_PATHS  # capped

    stored_qs = [tuple(p["q"]) for p in paths]
    oldest = tuple(sorted(_normalize_access_terms("recall token01 via bridge")))
    newest = tuple(sorted(_normalize_access_terms(f"recall token{n:02d} via bridge")))
    assert oldest not in stored_qs  # oldest evicted
    assert newest in stored_qs      # newest retained


# ============================ 6. de-dup repeat-poison ============================


@pytest.mark.asyncio
async def test_dedup_repeat_query_is_noop(make_memory):
    em = await make_memory(enabled=True)
    ep = Episode(user_input="repeat target", source="direct")
    await em.store(ep)

    first = await em.record_recall_access_path(
        ep.id, query="same exact query phrasing", bridge="recall"
    )
    assert first is True
    for _ in range(4):
        again = await em.record_recall_access_path(
            ep.id, query="same exact query phrasing", bridge="recall"
        )
        assert again is False
    assert len(_paths(em, ep.id)) == 1

    # Re-ordered words normalize to the same sorted key -> still deduped.
    reordered = await em.record_recall_access_path(
        ep.id, query="phrasing query exact same", bridge="recall"
    )
    assert reordered is False
    assert len(_paths(em, ep.id)) == 1


# ============================ 7. DIRECT-only whitelist ============================


@pytest.mark.asyncio
async def test_non_direct_source_refused(make_memory):
    em = await make_memory(enabled=True)
    ep = Episode(user_input="direct only target", source="direct")
    await em.store(ep)

    second = await em.record_recall_access_path(
        ep.id, query="hearsay lookup", bridge="peer",
        source=MemorySource.SECONDHAND.value,
    )
    assert second is False
    assert "reconsol_access_paths_json" not in _meta(em, ep.id)

    # REFLECTION is also non-DIRECT -> refused (DIRECT-only, no re-encode from a
    # synthesized fragment).
    refl = await em.record_recall_access_path(
        ep.id, query="reflection lookup", bridge="dream",
        source=MemorySource.REFLECTION.value,
    )
    assert refl is False
    assert "reconsol_access_paths_json" not in _meta(em, ep.id)


# ============================ 8. provenance present ============================


@pytest.mark.asyncio
async def test_provenance_fields_present_and_normalized(make_memory):
    em = await make_memory(enabled=True)
    ep = Episode(user_input="provenance target", source="direct")
    await em.store(ep)

    ok = await em.record_recall_access_path(
        ep.id, query="The Reactor's CORE!! breach", bridge="cross_agent",
        source=MemorySource.DIRECT.value,
    )
    assert ok is True
    entry = _paths(em, ep.id)[0]
    assert entry["bridge"] == "cross_agent"
    assert entry["src"] == MemorySource.DIRECT.value
    assert isinstance(entry["ts"], (int, float)) and entry["ts"] > 0
    # q is normalized: lowercased, [a-z0-9]{2,} tokens, deduped, sorted.
    assert entry["q"] == ["breach", "core", "reactor", "the"]


# ============================ 9. unknown id honest-degrade ============================


@pytest.mark.asyncio
async def test_unknown_id_honest_degrade(make_memory):
    em = await make_memory(enabled=True)
    ok = await em.record_recall_access_path(
        "nonexistent-episode-id", query="anything here", bridge="recall"
    )
    assert ok is False  # no crash, honest False


# ============================ 10. empty / no-token query ============================


@pytest.mark.asyncio
async def test_empty_or_whitespace_query_refused(make_memory):
    em = await make_memory(enabled=True)
    ep = Episode(user_input="empty query target", source="direct")
    await em.store(ep)

    for q in ("", "   ", "!!! ...", "a"):  # none yield a [a-z0-9]{2,} token
        ok = await em.record_recall_access_path(ep.id, query=q, bridge="recall")
        assert ok is False
    assert "reconsol_access_paths_json" not in _meta(em, ep.id)
