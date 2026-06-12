"""Episodic memory — long-term storage and recall of past operations.

Uses ChromaDB for persistence and semantic similarity search via ONNX
MiniLM embeddings.  Replaces the previous SQLite + keyword-overlap
implementation (Phase 14b).
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import heapq
import json
import logging
import math
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from probos.cognitive.importance_scorer import compute_importance
from probos.cognitive.similarity import jaccard_similarity
from probos.cognitive.temporal_context import serialize_tcm_vector, deserialize_tcm_vector
from probos.types import AnchorFrame, Episode, RecallScore, resolve_provenance
from probos.types import EBBINGHAUS_DEFAULT_STABILITY_SECONDS

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class RecallConfidence:
    """AD-979a: a Feeling-of-Knowing signal derived from the recall query.

    The cognitive-science framing (Hart 1965; Koriat's accessibility
    hypothesis 1993): a Feeling-of-Knowing is *computed from the accessibility*
    of partial retrieved information — not self-reported. ``recall()`` already
    computes ``similarity = 1.0 - distance`` for every candidate and then throws
    it away (a silent ``continue`` below ``relevance_threshold``). This carries
    that distribution out so a "0 returned" can be distinguished from "the best
    match was 0.65, just under the bar" (the *invisible miss*).

    Fields:
      * ``band`` — ``"strong"`` (confident recall, == what ``recall()`` returns),
        ``"weak"`` (something relevant is present but below the confident-recall
        bar — the invisible miss), or ``"none"`` (nothing usefully near).
      * ``best_similarity`` — max cosine similarity over the returned candidates
        (0.0 when none). The accessibility quantity the band is derived from.
      * ``candidate_count`` — how many candidates the vector store returned.
        ``0`` is *fast-absence* ("I have nothing on this"); ``> 0`` with a
        sub-threshold ``best_similarity`` is a *slow-gap* (a possible
        vocabulary-mismatch miss — the AD-979c hybrid-retrieval case).
      * ``query`` — the (truncated) query text, for logging/telemetry.
    """

    band: str
    best_similarity: float
    candidate_count: int
    query: str


def classify_recall_confidence(
    best_similarity: float,
    candidate_count: int,
    *,
    relevance_threshold: float,
    weak_floor: float,
) -> str:
    """AD-979a: pure band classifier for the recall-confidence signal.

    Accessibility-derived (Koriat) — the band is a function of the actual
    similarity distribution the store returned, never a self-report:

      * ``candidate_count <= 0``           -> ``"none"`` (fast-absence)
      * ``best_similarity >= relevance``   -> ``"strong"`` (confident recall)
      * ``best_similarity >= weak_floor``  -> ``"weak"`` (the invisible miss)
      * otherwise                          -> ``"none"`` (candidates too distant)

    Pure (no I/O); independently unit-tested.
    """
    if candidate_count <= 0:
        return "none"
    if best_similarity >= relevance_threshold:
        return "strong"
    if best_similarity >= weak_floor:
        return "weak"
    return "none"


_FTS_TOKEN_RE = re.compile(r"[a-z0-9]+")


def fts_or_query(query: str, *, min_token_len: int = 2) -> str:
    """AD-979c: turn a natural query into a FTS5 OR-of-keywords MATCH string.

    The dense (cosine) axis misses a memory when it was encoded under different
    vocabulary than the query (the vocabulary-mismatch gap). The sparse axis
    should surface it by ANY shared keyword, so a natural query is lowercased,
    split into alphanumeric tokens, deduped (order-preserving), and joined with
    ``OR`` (each token quoted so FTS5 treats it as a literal term, never an
    operator). Returns ``""`` when no usable token remains (the caller then
    skips the sparse axis). Pure (no I/O); independently unit-tested.
    """
    tokens = _FTS_TOKEN_RE.findall(query.lower())
    seen: set[str] = set()
    uniq: list[str] = []
    for t in tokens:
        if len(t) >= min_token_len and t not in seen:
            seen.add(t)
            uniq.append(t)
    if not uniq:
        return ""
    return " OR ".join(f'"{t}"' for t in uniq)


def reciprocal_rank_fusion(
    rankings: list[list[str]], *, k: int = 60
) -> list[tuple[str, float]]:
    """AD-979c: Reciprocal Rank Fusion of several ranked id lists.

    ``score(d) = sum over rankings r of 1 / (k + rank_r(d))`` with 1-based
    ranks. Rank-based (not score-based), so it fuses a cosine ranking and a
    BM25/FTS ranking without any score-scale calibration. Returns
    ``[(id, score), ...]`` sorted by score descending, ties broken by
    first-appearance order (stable). With a SINGLE ranking the output preserves
    that ranking's order exactly (``1/(k+1) > 1/(k+2) > ...``), so a disabled or
    empty sparse axis leaves the dense order byte-identical. Pure (no I/O).
    """
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    seq = 0
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            if item not in first_seen:
                first_seen[item] = seq
                seq += 1
    return sorted(scores.items(), key=lambda kv: (-kv[1], first_seen[kv[0]]))


def decide_recall_control(band: str) -> str:
    """AD-979b: pure metacognitive control policy (Nelson & Narens 1990).

    The monitor signal (the AD-979a Feeling-of-Knowing ``band``) drives a
    control action:

      * ``"strong"`` -> ``"accept"``  — confident recall, use it as-is.
      * ``"weak"``   -> ``"expand"``  — the invisible miss; something relevant
        is likely present but the query phrasing under-retrieved it, so
        re-query with reformulated/expanded variants before settling.
      * ``"none"``   -> ``"abstain"`` — genuine absence (or candidates too
        distant); expansion would only manufacture noise, so abstain honestly.

    Only ``weak`` triggers work, so the control loop adds zero cost on the happy
    path (``strong``) and on genuine absence (``none``). Pure; unit-tested.
    """
    if band == "strong":
        return "accept"
    if band == "weak":
        return "expand"
    return "abstain"


def recall_expansion_variants(query: str, *, max_n: int = 2) -> list[str]:
    """AD-979b: bounded query-expansion variants for the ``expand`` control move.

    Two complementary, cheap reformulations that bridge a query-side vocabulary
    gap (AD-979c bridges the stored side), highest-value first:
      1. a content-word "soup" — the query stripped of scaffolding/stopwords to
         its alphanumeric content tokens, which often embeds closer to a terse
         stored episode than a verbose question does, and
      2. the AD-584 question->declarative reformulation (helps Q->A recall).
    The AD-584 ``reformulate_query`` also yields a punctuation-stripped copy of
    the original; that is near-identical to the query (low expansion value), so
    only its genuinely-reformulated variant is used here. Order-preserving,
    deduped, excludes the original query, capped at ``max_n``. Pure (no I/O);
    unit-tested.
    """
    variants: list[str] = []
    original_norm = query.strip().lower()

    def _add(candidate: str) -> None:
        cand = candidate.strip()
        if cand and cand.lower() != original_norm and cand not in variants:
            variants.append(cand)

    # 1. content-word soup (lowercased, scaffolding removed) — most distinct.
    tokens = _FTS_TOKEN_RE.findall(query.lower())
    soup = " ".join(t for t in tokens if len(t) >= 2)
    _add(soup)

    # 2. the question->declarative reformulation, when it differs. reformulate_
    #    query returns [stripped] or [stripped, reformulated]; the last element
    #    is the genuine reformulation (the first is just the de-punctuated query).
    try:
        from probos.knowledge.embeddings import reformulate_query
        rq = reformulate_query(query)
        if len(rq) >= 2:
            _add(rq[-1])
    except Exception:
        logger.debug("AD-979b: reformulate_query unavailable for expansion", exc_info=True)

    return variants[:max_n]


def _episode_validity_check(episode: Episode, at_time: float) -> bool:
    """AD-579b: Check if an episode is temporally valid at a given time."""
    if episode.valid_until > 0 and episode.valid_until < at_time:
        return False
    if episode.valid_from > 0 and episode.valid_from > at_time:
        return False
    return True


@dataclasses.dataclass(frozen=True)
class _AnchorQueryView:
    """AD-607c: lightweight anchor-query shim for the recall anomaly gate.

    Mirrors the AnchorFrame attribute shape so ``score_anchor_mismatch`` can
    compare query anchors against ``Episode.anchors`` without coupling to the
    full AnchorFrame type.
    """
    watch_section: str = ""
    channel: str = ""
    department: str = ""
    trigger_agent: str = ""
    trigger_type: str = ""
    thread_id: str = ""
    # Backward-compatible dimension attrs (used by tests/helpers that pass
    # generic dimension names rather than AnchorFrame attribute names).
    temporal: str = ""
    spatial: str = ""
    social: str = ""
    causal: str = ""
    evidential: str = ""

# BF-289: ChromaDB 1.5.8 caps single-call batch size at 5461. All
# full-collection migration writes MUST chunk through this constant.
# 2000 keeps a generous safety margin and survives Chroma version
# bumps that might lower the cap further.
_MIGRATION_BATCH_SIZE = 2000


async def _iter_collection_pages(
    collection: Any,  # ChromaDB Collection
    *,
    include: list[str],
    page_size: int | None = None,
) -> "AsyncIterator[dict[str, Any]]":
    """AD-818a: stream a ChromaDB collection one bounded page at a time.

    Each page is fetched via ``asyncio.to_thread`` so (1) only one page is
    resident in memory at a time (problem #2) and (2) the event loop yields
    between pages, letting ``asyncio.wait_for`` cancel a long migration at a
    page boundary (problem #3).

    Yields the raw ChromaDB ``get`` result dict for each non-empty page
    (keys: ``ids`` plus whatever was requested in ``include``). Stops when a
    page returns fewer than the effective page size ids (the last page) or
    zero ids.

    R1: ``page_size`` defaults to ``None`` and the module global
    ``_MIGRATION_BATCH_SIZE`` is read INSIDE the body (call time), NOT bound as
    a default-argument value (def time). This is what lets tests monkeypatch
    ``episodic._MIGRATION_BATCH_SIZE`` to a small value and actually force
    multi-page behavior. Do NOT write ``page_size: int = _MIGRATION_BATCH_SIZE``.

    Rec2 — OFFSET-STABILITY PRECONDITION: this design writes page k before
    reading page k+1 (the old code read everything first). That is only safe
    because the three callers either ``upsert`` existing ids IN PLACE (no add,
    no delete, no reorder of the row set being paginated) or write to a
    separate sidecar. ChromaDB does not formally contract ``.get()`` ordering,
    so any future caller that ADDS or DELETES collection rows mid-iteration
    would make ``offset`` skip/double-read and must NOT use this helper.
    """
    effective = page_size if page_size is not None else _MIGRATION_BATCH_SIZE
    offset = 0
    while True:
        page = await asyncio.to_thread(
            collection.get, include=include, limit=effective, offset=offset
        )
        ids = (page or {}).get("ids") or []
        if not ids:
            return
        yield page
        # Rec3: at an exact multiple (e.g. 2N rows, page_size N) this does one
        # final get(offset=2N) returning zero ids before the `if not ids`
        # return above — correct (no dup, no infinite loop). Do NOT "optimize"
        # this `len(ids) < effective` early-return away.
        if len(ids) < effective:
            return
        offset += effective


# ---------------------------------------------------------------------------
# AD-873: Ebbinghaus episode decay helpers (pure; no I/O)
# ---------------------------------------------------------------------------

# Each unit of positive ACT-R activation (AD-567d recency+frequency
# reinforcement signal) grows an episode's stability by this fraction, so
# frequently/recently recalled memories accrue stability and decay slower
# (spaced repetition). Conservative so a single recall does not over-cement.
_STABILITY_REINFORCEMENT_GAIN: float = 0.25


def decayed_strength(strength: float, stability: float, delta_seconds: float) -> float:
    """AD-873: Ebbinghaus retention curve ``S(t) = S0 * e^(-dt/stability)``.

    ``strength`` is the baseline retention ``S0`` (1.0 = freshly encoded),
    ``stability`` is the decay time-constant in seconds, and ``delta_seconds``
    is the elapsed time ``dt`` since encoding/last reinforcement. Larger
    stability => slower decay. Pure (no I/O).

    Guards: a non-positive ``stability`` has no usable decay constant, and a
    non-positive ``delta_seconds`` means no elapsed time — both return
    ``strength`` unchanged.
    """
    if stability <= 0.0:
        return strength
    if delta_seconds <= 0.0:
        return strength
    return strength * math.exp(-delta_seconds / stability)


def reinforced_stability(stability: float, activation: float) -> float:
    """AD-873: Grow ``stability`` from the AD-567d reinforcement signal.

    Frequently/recently recalled episodes have higher ACT-R ``activation``
    (``ln(sum age^-d)``) and accrue stability, so they decay slower (spaced
    repetition). Monotonic non-decreasing in ``activation``. Never shrinks:
    a non-finite or non-positive ``activation`` (stale or never-accessed —
    the tracker returns ``-inf``) returns ``stability`` unchanged. Pure (no
    I/O).
    """
    if stability <= 0.0:
        return stability
    if not math.isfinite(activation) or activation <= 0.0:
        return stability
    return stability * (1.0 + _STABILITY_REINFORCEMENT_GAIN * activation)


# ---------------------------------------------------------------------------
# BF-103: Sovereign ID resolution helpers (DRY — one place for all callers)
# ---------------------------------------------------------------------------

def resolve_sovereign_id(agent: Any) -> str:
    """Resolve an agent's sovereign_id, falling back to agent.id if unavailable.

    This is the ONLY correct way to get an agent ID for episode storage.
    All episode agent_ids_json entries MUST use sovereign_id.
    """
    return getattr(agent, 'sovereign_id', None) or getattr(agent, 'id', str(agent))


def resolve_sovereign_id_from_slot(slot_id: str, identity_registry: Any) -> str:
    """Resolve a slot ID to a sovereign ID via the identity registry.

    Used during episode storage when only a slot_id string is available
    (not an agent object). Returns slot_id unchanged if no mapping found.
    """
    if not identity_registry:
        return slot_id
    cert = identity_registry.get_by_slot(slot_id)
    if cert:
        return cert.agent_uuid
    return slot_id


async def migrate_episode_agent_ids(
    episodic_memory: "EpisodicMemory",
    identity_registry: Any,
) -> int:
    """Migrate episode agent_ids from slot IDs to sovereign IDs.

    Scans all episodes in ChromaDB. For each agent_id in agent_ids_json,
    checks if it's a slot ID with a known sovereign_id mapping. If so,
    replaces the slot ID with the sovereign_id.

    Returns the number of episodes updated.
    """
    if not episodic_memory or not episodic_memory._collection:
        return 0
    if not identity_registry:
        return 0

    t0 = time.time()
    migrated = 0

    try:
        async for page in _iter_collection_pages(
            episodic_memory._collection, include=["metadatas", "documents"]
        ):
            ids_list = page.get("ids") or []
            metadatas = page.get("metadatas", [])
            documents = page.get("documents", [])

            # Collect batch for single upsert (BF-134: avoid per-episode round-trips)
            batch_ids: list[str] = []
            batch_metas: list[dict] = []
            batch_docs: list[str] = []

            for i, ep_id in enumerate(ids_list):
                meta = metadatas[i] if i < len(metadatas) else {}
                agent_ids_json = meta.get("agent_ids_json", "[]")
                try:
                    agent_ids = json.loads(agent_ids_json)
                except (json.JSONDecodeError, TypeError):
                    continue

                changed = False
                new_ids: list[str] = []
                for aid in agent_ids:
                    resolved = resolve_sovereign_id_from_slot(aid, identity_registry)
                    new_ids.append(resolved)
                    if resolved != aid:
                        changed = True

                if changed:
                    meta["agent_ids_json"] = json.dumps(new_ids)
                    doc = documents[i] if i < len(documents) else ""
                    # Recompute content hash after agent ID migration (AD-541e)
                    ep = EpisodicMemory._metadata_to_episode(ep_id, doc or "", meta)
                    meta["content_hash"] = compute_episode_hash(ep)
                    batch_ids.append(ep_id)
                    batch_metas.append(meta)
                    batch_docs.append(doc or "")

            # AD-818a: write this page's batch before fetching the next page so
            # only one page is resident at a time (problem #2) and the loop
            # yields between pages (problem #3). BF-289: page_size (2000) is
            # already <= ChromaDB's per-call cap (5461 in 1.5.8), so each page
            # is a single upsert. Per-page failure is logged but does NOT abort
            # the migration — committed pages persist so a re-run only needs to
            # redo the failed slice.
            if batch_ids:
                try:
                    await asyncio.to_thread(
                        episodic_memory._collection.upsert,
                        ids=batch_ids,
                        metadatas=batch_metas,
                        documents=batch_docs,
                    )
                    migrated += len(batch_ids)
                except Exception:
                    logger.warning(
                        "BF-103: page upsert of %d candidates failed during "
                        "sovereign-ID migration; continuing with remaining pages",
                        len(batch_ids),
                        exc_info=True,
                    )
                    continue

        elapsed = time.time() - t0
        if migrated > 0:
            logger.info(
                "BF-103: Migrated %d episodes from slot IDs to sovereign IDs (%.1fs)",
                migrated, elapsed,
            )
        else:
            logger.debug("BF-103: No episodes needed migration (%.1fs)", elapsed)
    except Exception:
        logger.warning("BF-103: Episode ID migration failed", exc_info=True)

    return migrated


async def migrate_anchor_metadata(episodic_memory: "EpisodicMemory") -> int:
    """AD-570: Promote anchor fields to top-level metadata for ChromaDB filtering.

    One-time startup migration. Scans all episodes. For each episode that has
    anchors_json but is missing anchor_department, extracts key anchor fields
    and writes them as top-level metadata via upsert.

    Follows BF-103 migration pattern. Returns count of episodes updated.
    """
    if not episodic_memory or not episodic_memory._collection:
        return 0

    t0 = time.time()
    migrated = 0

    try:
        async for page in _iter_collection_pages(
            episodic_memory._collection, include=["metadatas", "documents"]
        ):
            ids_list = page.get("ids") or []
            metadatas = page.get("metadatas", [])
            documents = page.get("documents", [])

            # Collect batch for single upsert (BF-134: avoid per-episode round-trips)
            batch_ids: list[str] = []
            batch_metas: list[dict] = []
            batch_docs: list[str] = []

            for i, ep_id in enumerate(ids_list):
                meta = metadatas[i] if i < len(metadatas) else {}
                # BF-134: Check for the newest promoted field, not just any promoted field.
                # Episodes migrated by AD-570 have anchor_department but lack anchor_watch_section.
                if "anchor_watch_section" in meta:
                    continue  # Already has all promoted fields

                anchors_json = meta.get("anchors_json", "")
                anchor_department = ""
                anchor_channel = ""
                anchor_trigger_type = ""
                anchor_trigger_agent = ""
                anchor_watch_section = ""

                if anchors_json:
                    try:
                        anchors_data = json.loads(anchors_json)
                        anchor_department = anchors_data.get("department", "") or ""
                        anchor_channel = anchors_data.get("channel", "") or ""
                        anchor_trigger_type = anchors_data.get("trigger_type", "") or ""
                        anchor_trigger_agent = anchors_data.get("trigger_agent", "") or ""
                        anchor_watch_section = anchors_data.get("watch_section", "") or ""
                    except (json.JSONDecodeError, TypeError):
                        pass

                meta["anchor_department"] = anchor_department
                meta["anchor_channel"] = anchor_channel
                meta["anchor_trigger_type"] = anchor_trigger_type
                meta["anchor_trigger_agent"] = anchor_trigger_agent
                meta["anchor_watch_section"] = anchor_watch_section

                batch_ids.append(ep_id)
                batch_metas.append(meta)
                batch_docs.append(documents[i] if i < len(documents) else "")

            # AD-818a: write this page's batch before fetching the next page.
            # BF-289: page_size (2000) is already <= ChromaDB's per-call cap, so
            # each page is a single upsert. Per-page failure is logged but does
            # NOT abort the migration.
            if batch_ids:
                docs_clean = [d or "" for d in batch_docs]
                try:
                    await asyncio.to_thread(
                        episodic_memory._collection.upsert,
                        ids=batch_ids,
                        metadatas=batch_metas,
                        documents=docs_clean,
                    )
                    migrated += len(batch_ids)
                except Exception:
                    logger.warning(
                        "AD-570: page upsert of %d candidates failed during "
                        "anchor metadata migration; continuing with remaining pages",
                        len(batch_ids),
                        exc_info=True,
                    )
                    continue

        elapsed = time.time() - t0
        if migrated > 0:
            logger.info(
                "AD-570: Promoted anchor metadata for %d episodes (%.1fs)",
                migrated, elapsed,
            )
        else:
            logger.debug("AD-570: No episodes needed anchor metadata migration (%.1fs)", elapsed)
    except Exception:
        logger.warning("AD-570: Anchor metadata migration failed", exc_info=True)

    return migrated


async def migrate_embedding_model(
    episodic_memory: "EpisodicMemory",
    model_name: str,
) -> int:
    """AD-584: Re-embed all episodes when the embedding model changes.

    Checks collection metadata for stored model name. If missing or different
    from the active model, deletes and recreates the collection with the new
    embedding function, re-adding all existing documents in batches.

    Must run AFTER collection creation, BEFORE any queries.
    Returns count of re-embedded episodes (0 if no migration needed).
    """
    if not episodic_memory or not episodic_memory._collection:
        return 0
    if not episodic_memory._client:
        return 0

    collection = episodic_memory._collection
    stored_model = ""
    try:
        meta = collection.metadata or {}
        stored_model = meta.get("embedding_model", "")
    except Exception:
        pass

    if stored_model == model_name:
        logger.debug("AD-584: Embedding model unchanged (%s), skipping migration", model_name)
        return 0

    t0 = time.time()
    migrated = 0

    try:
        # Read all existing documents
        existing = collection.get(include=["documents", "metadatas"])
        ids = existing.get("ids") or []
        documents = existing.get("documents") or []
        metadatas = existing.get("metadatas") or []

        if not ids:
            # No episodes to re-embed — just update metadata
            collection.modify(metadata={"embedding_model": model_name})
            logger.info("AD-584: No episodes to re-embed, updated collection metadata to %s", model_name)
            return 0

        # Delete and recreate collection with new embedding function
        from probos.knowledge.embeddings import get_embedding_function
        episodic_memory._client.delete_collection("episodes")
        ef = get_embedding_function()
        episodic_memory._collection = episodic_memory._client.get_or_create_collection(
            name="episodes",
            embedding_function=ef,
            metadata={
                "hnsw:space": "cosine",
                "embedding_model": model_name,
                "hnsw:sync_threshold": int(episodic_memory._hnsw_sync_threshold),
                "hnsw:batch_size": int(episodic_memory._hnsw_batch_size),
            },
        )

        # Re-add in batches of 100
        batch_size = 100
        for start in range(0, len(ids), batch_size):
            end = min(start + batch_size, len(ids))
            batch_ids = ids[start:end]
            batch_docs = [d or "" for d in documents[start:end]]
            batch_metas = metadatas[start:end]
            episodic_memory._collection.add(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_metas,
            )

        migrated = len(ids)
        elapsed = time.time() - t0
        logger.info(
            "AD-584: Re-embedded %d episodes with %s (%.1fs)",
            migrated, model_name, elapsed,
        )
    except Exception:
        logger.warning("AD-584: Embedding model migration failed (non-fatal)", exc_info=True)

    return migrated


async def migrate_participant_index(
    episodic_memory: "EpisodicMemory",
) -> int:
    """AD-570b: Backfill participant index from existing episodes.

    Reads agent_ids_json and anchors_json from all episodes,
    populates the participant index sidecar.
    """
    if not episodic_memory or not episodic_memory._collection:
        return 0
    if not episodic_memory._participant_index:
        return 0

    t0 = time.time()
    migrated = 0
    async for page in _iter_collection_pages(
        episodic_memory._collection, include=["metadatas"]
    ):
        ids = page.get("ids") or []
        metas = page.get("metadatas") or []

        page_batch = []
        for ep_id, meta in zip(ids, metas):
            # Parse agent_ids
            try:
                agent_ids = json.loads(meta.get("agent_ids_json", "[]"))
            except (json.JSONDecodeError, TypeError):
                agent_ids = []

            # Parse participants from anchors
            participants: list[str] = []
            anchors_raw = meta.get("anchors_json", "")
            if anchors_raw:
                try:
                    anchors_dict = json.loads(anchors_raw)
                    participants = anchors_dict.get("participants", [])
                except (json.JSONDecodeError, TypeError):
                    pass

            if agent_ids or participants:
                page_batch.append((ep_id, agent_ids, participants))

        # AD-818a: write this page's batch before fetching the next page.
        # record_episode_batch is already async, so no to_thread. R2: NO new
        # try/except — a failure here propagates to _run_one_migration's
        # honest-degrade wrapper exactly as today (wrapping it would hide a
        # failure that currently aborts the migration).
        if page_batch:
            await episodic_memory._participant_index.record_episode_batch(page_batch)
        # R3: accumulate the count of participating episodes across pages and
        # return that total — do NOT return record_episode_batch's return value.
        migrated += len(page_batch)

    elapsed = time.time() - t0
    logger.info("AD-570b: Participant index populated for %d episodes in %.1fs", migrated, elapsed)
    return migrated


async def migrate_enriched_embedding(
    episodic_memory: "EpisodicMemory",
) -> int:
    """AD-605: Re-embed all episodes with enriched document text.

    Reads all episodes, rebuilds documents via _prepare_document(), and
    re-adds with enriched text. Also populates the user_input metadata
    field for backward compatibility.

    AD-818a-2: streamed one bounded page at a time via
    ``_iter_collection_pages`` so only one page is resident in memory and the
    event loop yields between pages (lets ``_run_one_migration``'s
    ``asyncio.wait_for`` cancel at a page boundary). Each page is re-embedded
    with ONE batched in-place ``collection.update`` (offset-stable: update
    rewrites rows in place, so the pagination offset stays valid).

    Must run AFTER collection creation, BEFORE any queries.
    Returns count of re-embedded episodes (0 if no migration needed).
    """
    if not episodic_memory or not episodic_memory._collection:
        return 0

    collection = episodic_memory._collection
    meta = collection.metadata or {}
    version = meta.get("enriched_embedding_version", 0)

    if version >= 1:
        logger.debug("AD-605: Enriched embedding already applied (v%d), skipping", version)
        return 0

    t0 = time.time()
    migrated = 0

    try:
        async for page in _iter_collection_pages(
            collection, include=["documents", "metadatas"]
        ):
            ids = page.get("ids") or []
            documents = page.get("documents") or []
            metadatas = page.get("metadatas") or []

            page_ids: list[str] = []
            page_docs: list[str] = []
            page_metas: list[dict] = []

            for i, ep_id in enumerate(ids):
                ep_meta = metadatas[i] or {}
                original_doc = documents[i] or ""

                # Store original user_input if not already present
                if "user_input" not in ep_meta:
                    ep_meta["user_input"] = original_doc

                # Reconstruct minimal Episode for _prepare_document
                anchors_raw = ep_meta.get("anchors_json", "")
                anchors = AnchorFrame(**json.loads(anchors_raw)) if anchors_raw else None
                enriched_doc = EpisodicMemory._prepare_document(
                    Episode(
                        id=ep_id,
                        timestamp=float(ep_meta.get("timestamp", 0.0)),
                        user_input=original_doc,
                        dag_summary={},
                        outcomes=[],
                        agent_ids=[],
                        duration_ms=0.0,
                        anchors=anchors,
                    )
                )
                page_ids.append(ep_id)
                page_docs.append(enriched_doc)
                page_metas.append(ep_meta)

            # AD-818a-2: ONE batched in-place update per page (not per episode).
            # to_thread keeps the event loop responsive between pages so the
            # _run_one_migration wait_for can cancel at a page boundary.
            if page_ids:
                await asyncio.to_thread(
                    collection.update,
                    ids=page_ids,
                    documents=page_docs,
                    metadatas=page_metas,
                )
                migrated += len(page_ids)

        # Mark migration complete UNCONDITIONALLY (also covers the empty
        # collection: the async-for yields nothing and migrated stays 0).
        # Filter out ChromaDB internal keys (hnsw:space etc.) to avoid
        # "Changing the distance function" ValueError on modify().
        safe_meta = {k: v for k, v in meta.items() if not k.startswith("hnsw:")}
        collection.modify(metadata={**safe_meta, "enriched_embedding_version": 1})
        elapsed = time.time() - t0
        logger.info("AD-605: Re-embedded %d episodes with enriched text (%.1fs)", migrated, elapsed)
    except Exception:
        logger.warning("AD-605: Enriched embedding migration failed (non-fatal)", exc_info=True)

    return migrated


async def sweep_hash_integrity(
    episodic_memory: "EpisodicMemory",
    max_episodes: int = 200,
) -> int:
    """BF-207: Proactive hash integrity sweep on startup.

    Scans the most recent episodes and auto-heals any content hash
    mismatches left by an unclean shutdown. Runs AFTER all other
    migrations (BF-103, AD-570, AD-584, AD-605) which may change
    metadata that affects the hash.

    max_episodes=200 covers approximately 10 minutes of busy session
    activity. Crashed shutdowns typically only leave the last few
    episodes stale, but the generous budget costs little (sub-second
    for 200 episodes).

    AD-818a-2: streamed one bounded page at a time via
    ``_iter_collection_pages`` (problem #2). ChromaDB's .get() returns rows
    in INSERTION order, not timestamp order, so we cannot simply take the
    first page — every page is scanned and a bounded size-``max_episodes``
    min-heap retains only the newest episodes by timestamp. The heap is
    drained newest-first so the batched update lists episodes in descending
    (timestamp, seq) order, matching the pre-pagination sweep. Honest-degrade
    is owned by the _run_one_migration wrapper at the call site, so this
    function no longer swallows exceptions internally.

    Returns the number of episodes healed.
    """
    if not episodic_memory or not episodic_memory._collection:
        return 0

    collection = episodic_memory._collection

    # AD-818a-2: bounded min-heap keeps only the newest `max_episodes` episodes
    # resident while streaming. Heap entry: (timestamp, seq, ep_id, meta, doc).
    # `seq` is a monotonic int tiebreaker so heap comparison never falls through
    # to comparing dicts/None when timestamps are equal.
    heap: list[tuple[float, int, str, dict, str]] = []
    seq = 0
    async for page in _iter_collection_pages(
        collection, include=["metadatas", "documents"]
    ):
        ids_list = page.get("ids") or []
        metadatas = page.get("metadatas") or []
        documents = page.get("documents") or []
        for i, ep_id in enumerate(ids_list):
            meta = metadatas[i] if i < len(metadatas) else None
            doc = documents[i] if i < len(documents) else ""
            ts = float(meta.get("timestamp", 0)) if meta else 0.0
            heapq.heappush(heap, (ts, seq, ep_id, meta, doc))
            seq += 1
            if len(heap) > max_episodes:
                heapq.heappop(heap)  # evict oldest

    # Drain newest-first so the batched update lists episodes in descending
    # (timestamp, seq) order — REQUIRED for parity with the pre-pagination sweep.
    ordered = sorted(heap, key=lambda t: (t[0], t[1]), reverse=True)

    batch_ids: list[str] = []
    batch_metas: list[dict] = []

    for _ts, _seq, ep_id, meta, doc in ordered:
        if not meta:
            continue
        stored_hash = meta.get("content_hash", "")
        if not stored_hash:
            continue  # Legacy episode — no hash to verify

        ep = EpisodicMemory._metadata_to_episode(ep_id, doc or "", meta)
        recomputed = compute_episode_hash(ep)

        if recomputed != stored_hash:
            updated_meta = dict(meta)
            updated_meta["content_hash"] = recomputed
            updated_meta["_hash_v"] = _HASH_VERSION
            batch_ids.append(ep_id)
            batch_metas.append(updated_meta)

    # Batch update — ChromaDB's .update() accepts arrays natively
    healed = 0
    if batch_ids:
        collection.update(
            ids=batch_ids,
            metadatas=batch_metas,
        )
        healed = len(batch_ids)

    return healed


# ---------------------------------------------------------------------------
# AD-541e: Episode content hashing — cryptographic tamper detection
# ---------------------------------------------------------------------------

def compute_episode_hash(episode: Episode) -> str:
    """Compute SHA-256 content hash for an episode.

    Uses canonical JSON serialization (sorted keys, compact separators)
    following the Identity Ledger pattern (identity.py:135-148).

    Includes all content fields. Excludes:
    - id (document key, not content)
    - embedding (computed by ChromaDB, not original content)

    Values are normalized to match _episode_to_metadata storage coercions
    so the hash survives the ChromaDB round-trip.
    """
    content = {
        "timestamp": round(float(episode.timestamp or 0.0), 6),
        "user_input": episode.user_input,
        "dag_summary": episode.dag_summary,
        "outcomes": episode.outcomes,
        "reflection": episode.reflection or "",
        "agent_ids": episode.agent_ids,
        "duration_ms": float(episode.duration_ms),
        "shapley_values": episode.shapley_values,
        "trust_deltas": episode.trust_deltas,
        "source": episode.source or "direct",
    }
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_HASH_VERSION = 2  # Current hash normalization version


def _verify_episode_hash(
    episode: Episode,
    stored_hash: str,
    metadata: dict | None = None,
    collection: Any = None,
) -> bool:
    """Verify an episode's content matches its stored hash.

    Returns True if hash matches or no hash stored (legacy episode).
    Returns False only on hash mismatch (potential tampering).

    If collection is provided and the episode was stored with an older
    hash version (_hash_v < _HASH_VERSION), auto-heals the stale hash.
    """
    if not stored_hash:
        return True  # Legacy episode — no hash to verify
    recomputed = compute_episode_hash(episode)
    if recomputed != stored_hash:
        stored_v = metadata.get("_hash_v", 0) if metadata else 0
        # Auto-heal: update stale hash from version upgrade OR shutdown race (BF-207).
        # Shutdown can leave ChromaDB in a state where metadata doesn't match
        # the hash computed at store time. The data in ChromaDB is authoritative
        # (it's what will be used), so recompute the hash to match.
        if collection and metadata:
            try:
                updated_meta = dict(metadata)
                updated_meta["content_hash"] = recomputed
                updated_meta["_hash_v"] = _HASH_VERSION
                collection.update(
                    ids=[episode.id],
                    metadatas=[updated_meta],
                )
                if stored_v < _HASH_VERSION:
                    logger.info(
                        "AD-541e: Auto-healed hash v%d->v%d for episode %s",
                        stored_v, _HASH_VERSION, episode.id[:8],
                    )
                else:
                    logger.warning(
                        "BF-207: Repaired hash mismatch for episode %s "
                        "(likely shutdown race — stored=%s recomputed=%s)",
                        episode.id[:8], stored_hash[:12], recomputed[:12],
                    )
                return True
            except Exception:
                logger.debug("Auto-heal failed for %s", episode.id[:8], exc_info=True)
        # No collection available — can't heal, log warning only
        logger.warning(
            "Episode %s hash mismatch (v%d): stored=%s recomputed=%s",
            episode.id[:8] if episode.id else "unknown",
            stored_v, stored_hash[:12], recomputed[:12],
        )
        return False
    return True


def resolve_recall_tier_params(
    tier: str,
    tier_config: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve recall parameters for a given tier (AD-462c).

    Returns dict with keys: k, context_budget, anchor_confidence_gate,
    use_salience_weights, cross_department_anchors.
    Falls back to 'enhanced' tier defaults if tier not found.
    """
    defaults: dict[str, dict[str, Any]] = {
        "basic": {"k": 3, "context_budget": 1500, "anchor_confidence_gate": 0.0, "use_salience_weights": False, "cross_department_anchors": False},
        "enhanced": {"k": 5, "context_budget": 4000, "anchor_confidence_gate": 0.3, "use_salience_weights": True, "cross_department_anchors": False},
        "full": {"k": 8, "context_budget": 6000, "anchor_confidence_gate": 0.3, "use_salience_weights": True, "cross_department_anchors": True},
        "oracle": {"k": 10, "context_budget": 8000, "anchor_confidence_gate": 0.2, "use_salience_weights": True, "cross_department_anchors": True},
    }
    source = tier_config if tier_config else defaults
    return source.get(tier, source.get("enhanced", defaults["enhanced"]))


class EpisodicMemory:
    """ChromaDB-backed episodic memory with semantic similarity recall."""

    # BF-039: Throttling & deduplication constants
    MAX_EPISODES_PER_HOUR = 20  # per agent, rolling window
    SIMILARITY_WINDOW_MINUTES = 30
    SIMILARITY_THRESHOLD = 0.8  # Jaccard word-level

    def __init__(
        self,
        db_path: str | Path,
        max_episodes: int = 100_000,
        relevance_threshold: float = 0.7,
        verify_content_hash: bool = True,
        eviction_audit: Any = None,
        agent_recall_threshold: float = 0.25,
        fts_keyword_floor: float = 0.2,
        query_reformulation_enabled: bool = True,
        hnsw_sync_threshold: int = 64,
        hnsw_batch_size: int = 32,
        recall_rerank_enabled: bool = False,
        recall_rerank_weights: dict[str, float] | None = None,
        recall_confidence_weak_floor: float = 0.45,
        hybrid_recall_enabled: bool = False,
        hybrid_rrf_k: int = 60,
        recall_fok_logging_enabled: bool = False,
    ) -> None:
        self.db_path = str(db_path)
        self.max_episodes = max_episodes
        self.relevance_threshold = relevance_threshold
        # AD-979a: lower bound of the "weak" Feeling-of-Knowing band. A best
        # similarity in [weak_floor, relevance_threshold) is the *invisible
        # miss* (relevant-ish but under the confident-recall bar); below it is
        # "none". Default 0.45 (above the AD-655 contrastive band's 0.4 floor).
        self._recall_confidence_weak_floor = float(recall_confidence_weak_floor)
        # AD-979c: hybrid dense+sparse retrieval (off by default -> byte-identical).
        # When enabled, recall fuses the cosine ranking with the FTS5 keyword
        # ranking via Reciprocal Rank Fusion so a vocabulary-mismatched episode
        # (below the cosine threshold but keyword-present) is still surfaced.
        self._hybrid_recall_enabled = bool(hybrid_recall_enabled)
        self._hybrid_rrf_k = max(1, int(hybrid_rrf_k))
        # AD-981a: when set, recall_for_agent emits the agent-scoped AD-979a
        # Feeling-of-Knowing band per call (a calibration signal). Off by
        # default -> no extra log and byte-identical recalled episodes.
        self._recall_fok_logging = bool(recall_fok_logging_enabled)
        self._verify_on_recall = verify_content_hash
        self._eviction_audit = eviction_audit
        self._agent_recall_threshold = agent_recall_threshold  # BF-134
        self._fts_keyword_floor = fts_keyword_floor  # BF-134
        self._query_reformulation_enabled = query_reformulation_enabled  # AD-584
        # AD-821: cap batch_size at threshold//2 to keep batches strictly smaller
        # than the flush window (prevents batch-equals-window pathology where
        # every batch triggers a flush, defeating Chroma's batched-write path).
        self._hnsw_sync_threshold = int(hnsw_sync_threshold)
        self._hnsw_batch_size = max(1, min(int(hnsw_batch_size), self._hnsw_sync_threshold // 2))
        # AD-873: composite recall reranking (off + neutral by default).
        self._recall_rerank_enabled = bool(recall_rerank_enabled)
        self._recall_rerank_weights: dict[str, float] = dict(recall_rerank_weights or {})
        self._client: Any = None
        self._collection: Any = None
        self._fts_db: Any = None  # AD-567b: FTS5 sidecar
        self._activation_tracker: Any = None  # AD-567d: ACT-R activation tracker
        self._reconsolidation_scheduler: Any = None  # AD-574: spaced review scheduling
        self._storage_gate: Any = None  # AD-610: utility-based storage gate
        self._retroactive_evolver: Any = None  # AD-608: store-time metadata evolution
        self._anomaly_window_manager: Any = None  # AD-673: episode anomaly window stamping
        self._participant_index: Any = None  # AD-570b: Participant index sidecar
        self._tcm: Any = None  # AD-601: Temporal Context Model engine
        self._tcm_weight: float = 0.0             # AD-601: set by set_tcm() when wired
        self._tcm_fallback_watch_weight: float = 0.0   # AD-601: set by set_tcm() when wired
        self._security_config: Any = None  # AD-607: memory security config (validates recall)
        self._security_gate: Any = None  # AD-607h: store-time prompt-injection gate
        self._security_event_emitter: Any = None  # AD-607: emit hook for security events

    def set_activation_tracker(self, tracker: Any) -> None:
        """AD-567d: Wire the activation tracker after construction."""
        self._activation_tracker = tracker

    def set_reconsolidation_scheduler(self, scheduler: Any) -> None:
        """AD-574: Wire the reconsolidation scheduler after construction."""
        self._reconsolidation_scheduler = scheduler

    def set_storage_gate(self, gate: Any) -> None:
        """AD-610: Wire the storage gate for write-time validation."""
        self._storage_gate = gate

    def set_security_config(self, config: Any) -> None:
        """AD-607: Wire the memory security config (validates recall + emits anomaly events)."""
        self._security_config = config

    def set_security_gate(self, gate: Any) -> None:
        """AD-607h: Wire the memory security gate for store-time validation."""
        self._security_gate = gate

    def set_security_event_emitter(self, emitter: Any) -> None:
        """AD-607: Wire emit hook for memory security events.

        ``emitter`` is a callable ``(event_type, payload) -> None``. Failures
        are swallowed so security-event emission never breaks the memory path.
        """
        self._security_event_emitter = emitter

    def _emit_security_event(self, event_type: Any, payload: dict) -> None:
        """AD-607: emit a security event through the wired emitter (if any).

        Tier-1 swallow — security event emission must not break the memory
        path. Logged at debug level for diagnostics.
        """
        emit = getattr(self, "_security_event_emitter", None)
        if emit is None:
            return
        try:
            emit(event_type, payload)
        except Exception:
            logger.debug(
                "AD-607: security event emit failed for %s",
                event_type,
                exc_info=True,
            )

    def _security_anomaly_drop(
        self,
        episode: Episode,
        *,
        query: str = "",
        anchor_query: Any = None,
    ) -> bool:
        """AD-607a/b/c: recall-time anomaly gate. Returns True if caller
        should drop the episode under enforcement; emits the appropriate
        EventType when an anomaly fires (observational mode).
        """
        config = getattr(self, "_security_config", None)
        if config is None:
            return False
        try:
            from probos.cognitive.memory_security import (
                validate_recall_result,
                validate_provenance,
            )
            from probos.events import EventType

            validation = validate_recall_result(
                episode, query=query, anchor_query=anchor_query, config=config,
            )
            if not validation.anomalies:
                return False

            self._emit_security_event(EventType.MEMORY_RECALL_ANOMALY, {
                "episode_id": getattr(episode, "id", ""),
                "anomalies": list(validation.anomalies),
                "score": float(validation.score),
            })
            # Provenance-specific event (separate audit channel)
            ok, reason = validate_provenance(episode)
            if not ok:
                self._emit_security_event(EventType.MEMORY_PROVENANCE_GAP, {
                    "episode_id": getattr(episode, "id", ""),
                    "reason": reason,
                })
                if bool(getattr(config, "enforce_provenance", False)):
                    return True
            # Anchor-specific event when relevant
            if "anchor_mismatch" in validation.anomalies:
                self._emit_security_event(EventType.MEMORY_ANCHOR_MISMATCH, {
                    "episode_id": getattr(episode, "id", ""),
                    "score": float(validation.score),
                })

            if bool(getattr(config, "enforce_recall", False)):
                return True
            return False
        except Exception:
            logger.debug("AD-607: recall anomaly gate failed", exc_info=True)
            return False

    def set_retroactive_evolver(self, evolver: Any) -> None:
        """AD-608: Wire the retroactive evolver for store-time evolution."""
        self._retroactive_evolver = evolver

    def set_anomaly_window_manager(self, manager: Any) -> None:
        """AD-673: Wire anomaly window manager for episode stamping."""
        self._anomaly_window_manager = manager

    def set_participant_index(self, index: Any) -> None:
        """AD-570b: Wire the participant index after construction."""
        self._participant_index = index

    def set_tcm(self, tcm: Any) -> None:
        """AD-601: Wire the Temporal Context Model after construction.

        Reads scoring weights from the TCM's public config property (single source of truth).
        """
        self._tcm = tcm
        if tcm is not None:
            self._tcm_weight = tcm.config.weight
            self._tcm_fallback_watch_weight = tcm.config.fallback_watch_weight

    async def start(self) -> None:
        import chromadb
        from probos.knowledge.embeddings import get_embedding_function

        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(path=str(db_dir))
        ef = get_embedding_function()
        try:
            self._collection = self._client.get_or_create_collection(
                name="episodes",
                embedding_function=ef,
                metadata={
                    "hnsw:space": "cosine",
                    "hnsw:sync_threshold": int(self._hnsw_sync_threshold),
                    "hnsw:batch_size": int(self._hnsw_batch_size),
                },
            )
        except ValueError as exc:
            if "Embedding function conflict" in str(exc):
                # AD-584: Embedding function type changed (e.g. default → sentence_transformer).
                # Open WITHOUT embedding function so migration can read and re-embed.
                logger.warning("AD-584: Embedding function conflict detected — opening collection without EF for migration")
                self._collection = self._client.get_or_create_collection(
                    name="episodes",
                    metadata={
                        "hnsw:space": "cosine",
                        "hnsw:sync_threshold": int(self._hnsw_sync_threshold),
                        "hnsw:batch_size": int(self._hnsw_batch_size),
                    },
                )
                # Clear stale embedding_model metadata so migration detects the mismatch
                try:
                    self._collection.modify(metadata={"embedding_model": "__ef_conflict__"})
                except Exception:
                    pass
            else:
                raise

        # AD-584: Ensure collection metadata includes embedding model name
        from probos.knowledge.embeddings import get_embedding_model_name
        try:
            col_meta = self._collection.metadata or {}
            if "embedding_model" not in col_meta:
                self._collection.modify(metadata={
                    **col_meta,
                    "embedding_model": get_embedding_model_name(),
                })
        except Exception:
            logger.debug("AD-584: Could not set embedding_model metadata", exc_info=True)

        # AD-567b: FTS5 keyword search sidecar
        try:
            import aiosqlite
            fts_path = str(db_dir / "episode_fts.db")
            self._fts_db = await aiosqlite.connect(fts_path)
            await self._fts_db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS episode_fts USING fts5("
                "episode_id UNINDEXED, content, tokenize='porter unicode61')"
            )
            await self._fts_db.commit()
        except Exception:
            logger.debug("AD-567b: FTS5 sidecar init failed — keyword search disabled", exc_info=True)
            self._fts_db = None

    async def stop(self) -> None:
        # AD-567b: Close FTS5 sidecar
        if self._fts_db is not None:
            try:
                await self._fts_db.close()
            except Exception:
                pass
            self._fts_db = None
        # AD-570b: Close participant index
        if self._participant_index is not None:
            try:
                await self._participant_index.stop()
            except Exception:
                pass
            self._participant_index = None
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass  # Teardown cleanup — errors expected and harmless
        self._collection = None
        self._client = None

    # ---- seeding (warm boot) -----------------------------------------

    async def seed(self, episodes: list[Episode]) -> int:
        """Bulk-restore episodes preserving original IDs and timestamps.

        Used for warm boot — does NOT trigger normal store() flow (no
        knowledge store hooks, no eviction). Skips episodes whose IDs
        already exist in the collection.  Returns count of episodes seeded.
        """
        if not self._collection or not episodes:
            return 0

        seeded = 0
        # Batch add for efficiency — ChromaDB handles duplicates via upsert
        batch_ids: list[str] = []
        batch_docs: list[str] = []
        batch_metas: list[dict] = []

        # Check which IDs already exist
        existing_ids: set[str] = set()
        try:
            all_ids = [ep.id for ep in episodes]
            result = self._collection.get(ids=all_ids)
            if result and result["ids"]:
                existing_ids = set(result["ids"])
        except Exception:
            logger.debug("Checking existing episode IDs failed", exc_info=True)

        for ep in episodes:
            if ep.id in existing_ids:
                continue
            batch_ids.append(ep.id)
            batch_docs.append(self._prepare_document(ep))
            batch_metas.append(self._episode_to_metadata(ep))
            seeded += 1

        if batch_ids:
            try:
                self._collection.add(
                    ids=batch_ids,
                    documents=batch_docs,
                    metadatas=batch_metas,
                )
            except Exception as e:
                logger.warning("Seed batch add failed: %s", e)
                seeded = 0

        # AD-567b: Populate FTS5 sidecar for seeded episodes
        if seeded > 0 and self._fts_db is not None:
            try:
                for i, ep in enumerate(episodes):
                    if ep.id in existing_ids:
                        continue
                    fts_content = (ep.user_input or "") + " " + (ep.reflection or "")
                    await self._fts_db.execute(
                        "INSERT OR IGNORE INTO episode_fts(episode_id, content) VALUES (?, ?)",
                        (ep.id, fts_content),
                    )
                await self._fts_db.commit()
            except Exception:
                logger.debug("AD-567b: FTS5 seed failed", exc_info=True)

        # AD-570b: Populate participant index for seeded episodes
        if seeded > 0 and self._participant_index is not None:
            try:
                batch = []
                for ep in episodes:
                    if ep.id in existing_ids:
                        continue
                    participants = ep.anchors.participants if ep.anchors else []
                    batch.append((ep.id, ep.agent_ids, participants))
                if batch:
                    await self._participant_index.record_episode_batch(batch)
            except Exception:
                logger.debug("AD-570b: Participant index seed failed", exc_info=True)

        return seeded

    # ---- selective encoding gate ------------------------------------

    @staticmethod
    def should_store(episode: Episode) -> bool:
        """Selective Encoding Gate — biologically-inspired memory filter.

        Not every experience merits a memory. Skip noise; store signal.
        The brain encodes experiences with significance, novelty, or goal relevance.
        """
        text = episode.user_input or ""
        outcomes = episode.outcomes or []

        # Always store Captain-initiated interactions (high significance)
        if text.startswith("[1:1 with"):
            return True

        # Always store Ward Room posts (intentional social communication)
        # BF-039: WR episodes now pass through this gate; they should store
        # unless the content is explicitly filtered below (e.g. SystemQA noise)
        if "[Ward Room]" in text or "[Ward Room reply]" in text:
            # Still filter SystemQA noise posted to Ward Room
            if "[SystemQA]" in text:
                for o in outcomes:
                    if isinstance(o, dict) and not o.get("success", True):
                        return True
                return False
            return True

        # Always store failures (learning opportunities)
        for o in outcomes:
            if isinstance(o, dict) and not o.get("success", True):
                return True

        # Skip proactive no-response episodes (highest-volume noise)
        if "[Proactive thought" in text and "no response" in text.lower():
            return False

        # Skip QA routine passes (mechanical, no insight)
        if text.startswith("[SystemQA]"):
            for o in outcomes:
                if isinstance(o, dict) and not o.get("success", True):
                    return True  # QA failures ARE signal
            return False  # QA passes are noise

        # Skip episodes with no meaningful content
        for o in outcomes:
            if isinstance(o, dict):
                response = o.get("response", "")
                if isinstance(response, str) and response.strip() in ("", "[NO_RESPONSE]"):
                    continue
                return True  # Has a real response → store
        # No outcomes with real responses and not caught above
        if not outcomes:
            return True  # No outcomes metadata → store conservatively
        return False

    # ---- storage --------------------------------------------------

    async def store(self, episode: Episode) -> None:
        """Persist an episode. Evicts oldest if over max_episodes."""
        if not self._collection:
            return

        # AD-610: Utility-based storage gating
        _storage_gate = getattr(self, "_storage_gate", None)
        if _storage_gate is not None:
            try:
                decision = _storage_gate.evaluate(episode)
                if decision.action == "REJECT":
                    logger.debug(
                        "AD-610: Episode %s rejected by storage gate: %s; skipping persistence",
                        episode.id,
                        decision.reason,
                    )
                    return
                if decision.action == "MERGE":
                    logger.debug(
                        "AD-610: Episode %s merge suggested with %s; merge path is deferred",
                        episode.id,
                        decision.duplicate_of,
                    )
                    return
            except Exception:
                logger.debug(
                    "AD-610: Storage gate evaluation failed for %s; allowing episode to preserve memory continuity",
                    episode.id,
                    exc_info=True,
                )

        # AD-607h: store-time prompt-injection detection
        _security_gate = getattr(self, "_security_gate", None)
        if _security_gate is not None:
            try:
                from probos.events import EventType
                decision = _security_gate.evaluate_store(episode)
                if decision.matched_pattern:
                    self._emit_security_event(EventType.MEMORY_INJECTION_SUSPECTED, {
                        "episode_id": episode.id,
                        "pattern": decision.matched_pattern,
                        "reason": decision.reason,
                    })
                    if decision.action == "REJECT":
                        logger.warning(
                            "AD-607h: Episode %s rejected by memory security gate: %s; skipping persistence",
                            episode.id,
                            decision.matched_pattern,
                        )
                        return
            except Exception:
                logger.debug(
                    "AD-607h: Memory security gate evaluation failed for %s; allowing episode",
                    episode.id,
                    exc_info=True,
                )

        # BF-039: Per-agent rate limit
        if self._is_rate_limited(episode):
            logger.debug("Episode rate-limited for agent %s", episode.agent_ids)
            return

        # BF-039: Content similarity dedup
        if self._is_duplicate_content(episode):
            logger.debug("Episode deduplicated (similar content) for agent %s", episode.agent_ids)
            return

        # AD-598: Compute importance score at encoding time
        if episode.importance == 5:  # Only score if not already set (default)
            _importance = compute_importance(episode)
            if _importance != 5:
                # AD-871: Reconstruct frozen Episode via dataclasses.replace so
                # every carried field (incl. the provenance envelope:
                # source_type/confidence/verification_count/contradicted_by) is
                # preserved. A field-by-field copy silently drops new fields.
                episode = dataclasses.replace(episode, importance=_importance)

        anomaly_window_manager = getattr(self, "_anomaly_window_manager", None)
        if anomaly_window_manager is not None:
            try:
                active_window = anomaly_window_manager.get_active_window()
            except Exception:
                logger.debug(
                    "AD-673: Failed to query anomaly window before storing episode %s; storing without stamp",
                    episode.id,
                    exc_info=True,
                )
                active_window = None
            if active_window and episode.anchors is not None:
                new_anchors = dataclasses.replace(
                    episode.anchors,
                    anomaly_window_id=active_window,
                )
                episode = dataclasses.replace(episode, anchors=new_anchors)
                anomaly_window_manager.record_episode_stamped()

        metadata = self._episode_to_metadata(episode)

        # AD-541b: Write-once guard — prevent silent episode overwrites
        existing = self._collection.get(ids=[episode.id])
        if existing and existing["ids"]:
            logger.warning(
                "Episode %s already exists — skipping store (write-once)",
                episode.id[:12],
            )
            return  # Do not overwrite

        # AD-601: Capture TCM context vector snapshot at encoding time.
        # Placed AFTER all admission gates (rate limit, dedup, write-once) so
        # context only drifts on successful writes. Rejected episodes must not
        # shift the context sequence.
        _tcm_vector: list[float] | None = None
        if getattr(self, '_tcm', None) is not None:
            try:
                _tcm_vector = self._tcm.update(
                    episode.user_input or "",
                    timestamp=episode.timestamp,
                )
            except Exception:
                logger.debug("AD-601: TCM update failed", exc_info=True)

        # AD-601: Inject TCM vector into metadata after admission gates
        if _tcm_vector is not None:
            metadata["tcm_vector_json"] = serialize_tcm_vector(_tcm_vector)
        else:
            metadata["tcm_vector_json"] = ""

        self._collection.add(
            ids=[episode.id],
            documents=[self._prepare_document(episode)],
            metadatas=[metadata],
        )

        # AD-567b: FTS5 dual-write
        if self._fts_db is not None:
            try:
                fts_content = (episode.user_input or "") + " " + (episode.reflection or "")
                await self._fts_db.execute(
                    "INSERT INTO episode_fts(episode_id, content) VALUES (?, ?)",
                    (episode.id, fts_content),
                )
                await self._fts_db.commit()
            except Exception:
                logger.debug("AD-567b: FTS5 insert failed for %s", episode.id[:8], exc_info=True)

        # AD-570b: Participant index dual-write
        if self._participant_index is not None:
            try:
                participants = episode.anchors.participants if episode.anchors else []
                await self._participant_index.record_episode(
                    episode.id, episode.agent_ids, participants,
                )
            except Exception:
                logger.debug("AD-570b: Participant index insert failed for %s", episode.id[:8], exc_info=True)

        reconsolidation_scheduler = getattr(self, "_reconsolidation_scheduler", None)
        if reconsolidation_scheduler is not None and episode.importance >= 7:
            try:
                reconsolidation_scheduler.schedule_review(episode.id, episode.importance)
            except Exception:
                logger.debug(
                    "AD-574: Failed to schedule reconsolidation for episode %s",
                    episode.id,
                    exc_info=True,
                )

        retroactive_evolver = getattr(self, "_retroactive_evolver", None)
        if retroactive_evolver is not None:
            try:
                await retroactive_evolver.evolve_on_store(episode)
            except Exception:
                logger.debug(
                    "AD-608: Retroactive evolution failed for episode %s",
                    episode.id,
                    exc_info=True,
                )

        # Evict oldest beyond budget
        await self._evict()

    async def get_episode_metadata(
        self,
        episode_id: str,
    ) -> dict[str, Any] | None:
        """AD-608: Retrieve metadata for a single episode."""
        if not self._collection:
            return None

        try:
            result = self._collection.get(ids=[episode_id], include=["metadatas"])
            if not result or not result.get("ids"):
                return None
            return result["metadatas"][0] if result.get("metadatas") else None
        except Exception:
            logger.debug(
                "AD-608: Failed to get metadata for episode %s",
                episode_id,
                exc_info=True,
            )
            return None

    async def list_episodes(self, *, limit: int | None = None) -> list[Episode]:
        """AD-689: Return episodes ordered by timestamp DESC.

        Used by EdgeBackfillService.backfill_episodes to walk the full
        collection once. Returns [] if the collection is unavailable.
        ``limit=None`` returns all rows; pass a non-negative int to cap
        the slice. Missing/malformed rows are silently skipped.
        """
        if not self._collection:
            return []
        try:
            result = self._collection.get(include=["metadatas", "documents"])
        except Exception:
            logger.debug("AD-689: list_episodes ChromaDB query failed", exc_info=True)
            return []
        if not result or not result.get("ids"):
            return []
        ids = result["ids"]
        metas = result.get("metadatas") or [{} for _ in ids]
        docs = result.get("documents") or ["" for _ in ids]
        paired = list(zip(ids, metas, docs))
        paired.sort(key=lambda x: (x[1] or {}).get("timestamp", 0), reverse=True)
        if limit is not None and limit >= 0:
            paired = paired[:limit]
        out: list[Episode] = []
        for ep_id, meta, doc in paired:
            try:
                out.append(self._metadata_to_episode(ep_id, doc or "", meta or {}))
            except Exception:
                logger.debug("AD-689: failed to reconstruct episode %s", ep_id, exc_info=True)
                continue
        return out

    async def get_by_ids(self, episode_ids: list[str]) -> list[Episode]:
        """AD-657: Fetch full Episode objects by ID, preserving input order.

        Missing IDs (e.g., evicted by AD-593 activation pruning) are silently
        omitted — caller treats absence as graceful degradation, not error.
        """
        if not self._collection or not episode_ids:
            return []
        try:
            result = self._collection.get(
                ids=list(episode_ids),
                include=["metadatas", "documents"],
            )
        except Exception:
            logger.debug("AD-657: get_by_ids ChromaDB query failed", exc_info=True)
            return []
        if not result or not result.get("ids"):
            return []

        by_id: dict[str, Episode] = {}
        result_ids = result["ids"]
        result_metas = result.get("metadatas") or [{} for _ in result_ids]
        result_docs = result.get("documents") or ["" for _ in result_ids]
        for i, doc_id in enumerate(result_ids):
            try:
                meta = result_metas[i] if i < len(result_metas) else {}
                doc = result_docs[i] if i < len(result_docs) else ""
                by_id[doc_id] = self._metadata_to_episode(doc_id, doc or "", meta or {})
            except Exception:
                logger.debug(
                    "AD-657: failed to reconstruct episode %s", doc_id, exc_info=True,
                )
                continue
        return [by_id[eid] for eid in episode_ids if eid in by_id]

    async def update_episode_metadata(
        self,
        episode_id: str,
        metadata_updates: dict[str, Any],
    ) -> bool:
        """AD-608: Update metadata fields on an existing episode."""
        if not self._collection:
            return False

        try:
            result = self._collection.get(ids=[episode_id], include=["metadatas"])
            if not result or not result.get("ids"):
                logger.warning(
                    "AD-608: Episode %s not found; cannot update metadata and relation propagation will skip it",
                    episode_id,
                )
                return False

            existing_meta = result["metadatas"][0] if result.get("metadatas") else {}
            merged = {**existing_meta, **metadata_updates}

            self._collection.update(ids=[episode_id], metadatas=[merged])
            return True
        except Exception:
            logger.debug(
                "AD-608: Failed to update metadata for episode %s",
                episode_id,
                exc_info=True,
            )
            return False

    async def sweep_episode_decay(
        self,
        activation_tracker: Any = None,
        *,
        limit: int = 500,
    ) -> dict[str, int]:
        """AD-873: Idle-time Ebbinghaus decay pass over a bounded page of episodes.

        Recomputes each episode's ``stability`` and ``strength`` and writes them
        back to ChromaDB metadata. Stability is recomputed IDEMPOTENTLY from the
        default baseline reinforced by the AD-567d ACT-R activation signal (so
        frequently/recently recalled episodes accrue stability and decay slower
        — spaced repetition), then ``strength = decayed_strength(1.0,
        stability, age)``. Recomputing from the baseline (rather than
        compounding the stored stability) means repeated sweeps converge instead
        of drifting.

        Bounded: only the first ``limit`` episodes are visited per call — never a
        full-collection rewrite. Honest-degrade: a failure on any single episode
        is logged and skipped, and a top-level failure returns the partial
        counts. Decay must NEVER abort the dream cycle.

        Returns ``{"swept": N, "reinforced": M}`` where ``swept`` is the number
        of episodes successfully written and ``reinforced`` is how many had a
        positive activation signal that grew their stability.
        """
        counts = {"swept": 0, "reinforced": 0}
        if not self._collection:
            return counts

        try:
            page = await asyncio.to_thread(
                self._collection.get,
                include=["metadatas"],
                limit=limit,
                offset=0,
            )
        except Exception:
            logger.debug("AD-873: episode decay sweep page read failed", exc_info=True)
            return counts

        ids = (page or {}).get("ids") or []
        if not ids:
            return counts
        metas = page.get("metadatas") or [{} for _ in ids]

        # AD-567d: batch the reinforcement signal so revisited memories decay
        # slower. Missing tracker / failure => neutral (-inf) activation for all.
        activations: dict[str, float] = {}
        if activation_tracker is not None:
            try:
                activations = activation_tracker.get_activations_batch(list(ids)) or {}
            except Exception:
                logger.debug("AD-873: activation batch query failed", exc_info=True)
                activations = {}

        now = time.time()
        for i, ep_id in enumerate(ids):
            try:
                meta = metas[i] if i < len(metas) else {}
                ep = self._metadata_to_episode(ep_id, "", meta or {})
                activation = activations.get(ep_id, float("-inf"))
                new_stability = reinforced_stability(
                    EBBINGHAUS_DEFAULT_STABILITY_SECONDS, activation
                )
                age = max(0.0, now - float(ep.timestamp or now))
                new_strength = decayed_strength(1.0, new_stability, age)
                ok = await self.update_episode_metadata(
                    ep_id,
                    {"strength": float(new_strength), "stability": float(new_stability)},
                )
                if ok:
                    counts["swept"] += 1
                    if math.isfinite(activation) and activation > 0.0:
                        counts["reinforced"] += 1
            except Exception:
                logger.debug(
                    "AD-873: episode decay failed for %s; skipping", ep_id, exc_info=True
                )
                continue

        return counts

    async def update_episode_validity(self, episode_id: str, valid_until: float) -> bool:
        """AD-579c: Update valid_until metadata for an existing episode."""
        if not self._collection:
            return False

        try:
            result = self._collection.get(ids=[episode_id], include=["metadatas"])
        except Exception:
            logger.debug("AD-579c: Failed to load episode %s for validity update", episode_id[:8], exc_info=True)
            return False

        if not result or not result.get("ids"):
            return False

        metadatas = result.get("metadatas") or []
        if not metadatas or metadatas[0] is None:
            return False

        metadata = dict(metadatas[0])
        metadata["valid_until"] = float(valid_until)

        try:
            self._collection.update(ids=[episode_id], metadatas=[metadata])
        except Exception:
            logger.debug("AD-579c: Failed to update validity for episode %s", episode_id[:8], exc_info=True)
            return False
        return True

    def _force_update(self, episode: Episode) -> None:
        """Bypass write-once for migration only. Do not call from normal code paths."""
        if not self._collection:
            return
        # AD-541f: Log the overwrite (best-effort, sync path)
        if self._eviction_audit:
            agent_id = episode.agent_ids[0] if episode.agent_ids else "unknown"
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._eviction_audit.record_eviction(
                        episode_id=episode.id,
                        agent_id=agent_id,
                        reason="force_update",
                        process="_force_update",
                        details="migration overwrite",
                        episode_timestamp=episode.timestamp,
                    ))
            except Exception:
                pass  # Best-effort audit for sync path
        metadata = self._episode_to_metadata(episode)
        self._collection.upsert(
            ids=[episode.id],
            documents=[self._prepare_document(episode)],
            metadatas=[metadata],
        )

    async def _evict(self) -> None:
        assert self._collection
        count = self._collection.count()
        if count > self.max_episodes:
            excess = count - self.max_episodes
            # Get oldest episodes by timestamp
            result = self._collection.get(
                include=["metadatas"],
            )
            if result and result["ids"] and result["metadatas"]:
                # Sort by timestamp ascending (oldest first)
                paired = list(zip(result["ids"], result["metadatas"]))
                paired.sort(key=lambda x: x[1].get("timestamp", 0))
                to_evict = paired[:excess]
                ids_to_delete = [p[0] for p in to_evict]
                # AD-541f: Record evictions before deletion
                if ids_to_delete and self._eviction_audit:
                    records = []
                    for eid, meta in to_evict:
                        agent_ids_raw = meta.get("agent_ids_json", "[]")
                        try:
                            agent_ids = json.loads(agent_ids_raw)
                            agent_id = agent_ids[0] if agent_ids else "unknown"
                        except (json.JSONDecodeError, TypeError):
                            agent_id = "unknown"
                        records.append({
                            "episode_id": eid,
                            "agent_id": agent_id,
                            "content_hash": meta.get("content_hash", ""),
                            "episode_timestamp": meta.get("timestamp", 0.0),
                        })
                    try:
                        await self._eviction_audit.record_batch_eviction(
                            records,
                            reason="capacity",
                            process="_evict",
                            details=f"batch of {len(ids_to_delete)}, budget={self.max_episodes}",
                        )
                    except Exception as exc:
                        logger.warning("Eviction audit failed: %s", exc)
                if ids_to_delete:
                    self._collection.delete(ids=ids_to_delete)
                    # AD-567b: FTS5 cleanup on eviction
                    if self._fts_db is not None:
                        try:
                            for eid in ids_to_delete:
                                await self._fts_db.execute(
                                    "DELETE FROM episode_fts WHERE episode_id = ?", (eid,)
                                )
                            await self._fts_db.commit()
                        except Exception:
                            logger.debug("AD-567b: FTS5 eviction cleanup failed", exc_info=True)
                    # AD-567d: Clean up activation records for evicted episodes
                    if self._activation_tracker:
                        try:
                            await self._activation_tracker.delete_episode_accesses(ids_to_delete)
                        except Exception:
                            logger.debug("AD-567d: Activation cleanup on eviction failed", exc_info=True)
                    # AD-570b: Participant index cleanup on eviction
                    if self._participant_index:
                        try:
                            await self._participant_index.delete_episodes(ids_to_delete)
                        except Exception:
                            logger.debug("AD-570b: Participant index eviction cleanup failed", exc_info=True)

    async def evict_by_ids(self, episode_ids: list[str], reason: str = "activation_pruning") -> int:
        """AD-567d: Evict specific episodes by ID. Handles audit, FTS5, ChromaDB, and activation cleanup.

        Used by dream Step 12 for activation-based pruning.
        Returns count of episodes actually evicted.
        """
        if not self._collection or not episode_ids:
            return 0

        # Gather metadata for audit trail
        evicted = 0
        try:
            result = self._collection.get(ids=episode_ids, include=["metadatas"])
            if not result or not result["ids"]:
                return 0

            valid_ids = result["ids"]

            # AD-541f: Record evictions before deletion
            if valid_ids and self._eviction_audit:
                records = []
                for i, eid in enumerate(valid_ids):
                    meta = result["metadatas"][i] if result["metadatas"] and i < len(result["metadatas"]) else {}
                    agent_ids_raw = meta.get("agent_ids_json", "[]")
                    try:
                        agent_ids = json.loads(agent_ids_raw)
                        agent_id = agent_ids[0] if agent_ids else "unknown"
                    except (json.JSONDecodeError, TypeError):
                        agent_id = "unknown"
                    records.append({
                        "episode_id": eid,
                        "agent_id": agent_id,
                        "content_hash": meta.get("content_hash", ""),
                        "episode_timestamp": meta.get("timestamp", 0.0),
                    })
                try:
                    await self._eviction_audit.record_batch_eviction(
                        records,
                        reason=reason,
                        process="evict_by_ids",
                        details=f"batch of {len(valid_ids)}, reason={reason}",
                    )
                except Exception as exc:
                    logger.warning("Eviction audit failed: %s", exc)

            # Delete from ChromaDB
            self._collection.delete(ids=valid_ids)
            evicted = len(valid_ids)

            # AD-567b: FTS5 cleanup
            if self._fts_db is not None:
                try:
                    for eid in valid_ids:
                        await self._fts_db.execute(
                            "DELETE FROM episode_fts WHERE episode_id = ?", (eid,)
                        )
                    await self._fts_db.commit()
                except Exception:
                    logger.debug("AD-567b: FTS5 eviction cleanup failed", exc_info=True)

            # AD-567d: Activation cleanup
            if self._activation_tracker:
                try:
                    await self._activation_tracker.delete_episode_accesses(valid_ids)
                except Exception:
                    logger.debug("AD-567d: Activation cleanup failed", exc_info=True)

            # AD-570b: Participant index cleanup
            if self._participant_index:
                try:
                    await self._participant_index.delete_episodes(valid_ids)
                except Exception:
                    logger.debug("AD-570b: Participant index eviction cleanup failed", exc_info=True)

        except Exception as e:
            logger.debug("evict_by_ids failed: %s", e)

        return evicted

    async def get_episode_ids_older_than(self, cutoff_timestamp: float) -> list[str]:
        """AD-567d: Return IDs of episodes with timestamp < cutoff_timestamp.

        Used by dream Step 12 to identify candidates for activation-based pruning.
        Only episodes older than the cutoff are eligible for pruning — never prune
        episodes less than 24 hours old.
        """
        if not self._collection:
            return []
        try:
            result = self._collection.get(
                where={"timestamp": {"$lt": cutoff_timestamp}},
                include=[],  # Only need IDs
            )
            return result["ids"] if result and result["ids"] else []
        except Exception:
            logger.debug("AD-567d: get_episode_ids_older_than failed", exc_info=True)
            return []

    def _is_rate_limited(self, episode: Episode) -> bool:
        """BF-039/BF-048: Check if agent has exceeded episode rate limit in the last hour."""
        if not episode.agent_ids:
            return False
        agent_id = episode.agent_ids[0]
        one_hour_ago = time.time() - 3600
        try:
            # Use get() with where filter for timestamp range
            recent = self._collection.get(
                where={"timestamp": {"$gte": one_hour_ago}},
                include=["metadatas"],
            )
        except Exception as exc:
            # BF-048: Fail CLOSED on query error — assume rate limited to prevent flooding
            logger.debug("Rate limit query failed (fail-closed): %s", exc)
            return True
        count = 0
        for meta in (recent.get("metadatas") or []):
            try:
                _ids = json.loads(meta.get("agent_ids_json", "[]"))
            except (json.JSONDecodeError, TypeError):
                _ids = []
            if agent_id in _ids:
                count += 1
        return count >= self.MAX_EPISODES_PER_HOUR

    def _is_duplicate_content(self, episode: Episode) -> bool:
        """BF-039: Check if a very similar episode was stored recently for same agent."""
        if not episode.agent_ids or not episode.user_input:
            return False
        agent_id = episode.agent_ids[0]
        window_start = time.time() - (self.SIMILARITY_WINDOW_MINUTES * 60)
        try:
            recent = self._collection.get(
                where={"timestamp": {"$gte": window_start}},
                include=["metadatas", "documents"],
            )
        except Exception:
            logger.debug("Episodic memory operation failed", exc_info=True)
            return False
        episode_words = set(episode.user_input.lower().split())
        for i, meta in enumerate(recent.get("metadatas") or []):
            try:
                _ids = json.loads(meta.get("agent_ids_json", "[]"))
            except (json.JSONDecodeError, TypeError):
                _ids = []
            if agent_id not in _ids:
                continue
            doc = (recent.get("documents") or [None])[i]
            if not doc:
                continue
            existing_words = set(doc.lower().split())
            if jaccard_similarity(episode_words, existing_words) >= self.SIMILARITY_THRESHOLD:
                return True
        return False

    # ---- recall ---------------------------------------------------

    @staticmethod
    def _composite_recall_score(
        similarity: float,
        episode: Episode,
        weights: dict[str, float],
        now: float,
    ) -> float:
        """AD-873: Multiplicative composite recall score for reranking.

        Combines semantic ``similarity`` with per-episode ``strength``,
        ``recency`` (Ebbinghaus-style ``exp(-age_hours/168)``), ``importance``
        (1-10 normalized to [0,1]) and optionally AD-871 ``confidence``, each
        normalized to [0,1] and raised to its configured weight. A weight of
        ``0.0`` neutralizes its factor (``x**0 == 1``), so all-zero weights
        reduce the score to ``similarity`` — reproducing today's semantic-only
        ordering. Pure (no I/O).
        """
        def _clamp01(x: float) -> float:
            if x < 0.0:
                return 0.0
            if x > 1.0:
                return 1.0
            return x

        score = _clamp01(similarity)
        w_s = float(weights.get("strength", 0.0))
        if w_s:
            score *= _clamp01(episode.strength) ** w_s
        w_r = float(weights.get("recency", 0.0))
        if w_r:
            age_hours = max(0.0, (now - float(episode.timestamp or now)) / 3600.0)
            score *= _clamp01(math.exp(-age_hours / 168.0)) ** w_r
        w_i = float(weights.get("importance", 0.0))
        if w_i:
            score *= _clamp01(float(episode.importance) / 10.0) ** w_i
        w_c = float(weights.get("confidence", 0.0))
        if w_c:
            score *= _clamp01(episode.confidence) ** w_c
        return score

    async def recall(self, query: str, k: int = 5) -> list[Episode]:
        """Semantic search — return top-k episodes by embedding similarity.

        AD-873: when composite reranking is enabled the full candidate pool is
        scored by ``strength * similarity * recency * importance`` and the top-k
        are returned; otherwise behaviour is unchanged (semantic-only).

        AD-979a: thin shim over :meth:`recall_with_confidence` (which is the
        single source of truth for the query+filter+rerank path). Callers that
        want the Feeling-of-Knowing signal call ``recall_with_confidence``
        directly; ``recall`` stays a drop-in returning just the episodes.
        """
        episodes, _confidence = await self.recall_with_confidence(query, k)
        return episodes

    async def recall_with_confidence(
        self, query: str, k: int = 5
    ) -> tuple[list[Episode], RecallConfidence]:
        """AD-979a: semantic recall PLUS a Feeling-of-Knowing confidence signal.

        Same query/filter/rerank path as the historical ``recall()`` (which now
        delegates here), but it also surfaces the similarity distribution
        ``recall()`` used to discard: the best candidate similarity and the
        candidate count, classified into a ``strong``/``weak``/``none`` band
        (see :class:`RecallConfidence`). The episode list returned is exactly
        what ``recall()`` returns (byte-identical) — the only addition is the
        signal, so the *invisible miss* (best match just under the bar) becomes
        visible to the caller (AD-979b acts on it).

        The vector store returns candidates in similarity-descending order, so
        the best similarity is the first candidate's — no extra scan needed.
        """
        _none = RecallConfidence(
            band="none", best_similarity=0.0, candidate_count=0, query=query[:200],
        )
        if not self._collection:
            return [], _none

        if not query.strip():
            return [], _none

        count = self._collection.count()
        if count == 0:
            return [], _none

        rerank = self._recall_rerank_enabled
        # AD-873: widen the candidate pool when reranking so the composite
        # score has material to reorder; otherwise keep the historical window.
        n_results = min(k * (10 if rerank else 3), count)
        result = self._collection.query(
            query_texts=[query],
            n_results=n_results,
            include=["metadatas", "documents", "distances"],
        )

        if not result or not result["ids"] or not result["ids"][0]:
            return [], _none

        # AD-979a: the FoK signal is derived from the raw similarity
        # distribution (Koriat accessibility), BEFORE the relevance-threshold /
        # security filters below. Candidates come back similarity-descending, so
        # the first is the most accessible; candidate_count distinguishes
        # fast-absence (0) from a slow-gap (candidates present, best < bar).
        distances0 = result["distances"][0] if result["distances"] else []
        candidate_count = len(result["ids"][0])
        best_similarity = (1.0 - distances0[0]) if distances0 else 0.0
        confidence = RecallConfidence(
            band=classify_recall_confidence(
                best_similarity,
                candidate_count,
                relevance_threshold=self.relevance_threshold,
                weak_floor=self._recall_confidence_weak_floor,
            ),
            best_similarity=best_similarity,
            candidate_count=candidate_count,
            query=query[:200],
        )

        episodes: list[Episode] = []
        scored: list[tuple[Episode, float]] = []  # AD-873: (episode, composite)
        now = time.time()
        for i, doc_id in enumerate(result["ids"][0]):
            # ChromaDB cosine distance: distance = 1 - similarity
            distance = result["distances"][0][i] if result["distances"] else 0.0
            similarity = 1.0 - distance

            if similarity < self.relevance_threshold:
                continue

            metadata = result["metadatas"][0][i] if result["metadatas"] else {}
            document = result["documents"][0][i] if result["documents"] else ""
            ep = self._metadata_to_episode(doc_id, document, metadata)

            # AD-607a: recall-time anomaly gate (observational by default)
            if self._security_anomaly_drop(ep, query=query, anchor_query=None):
                continue

            if rerank:
                # AD-873: collect the FULL pool (no early break) for reranking.
                composite = self._composite_recall_score(
                    similarity, ep, self._recall_rerank_weights, now
                )
                scored.append((ep, composite))
                continue

            episodes.append(ep)

            if len(episodes) >= k:
                break

        if rerank:
            # Stable sort by composite desc. ChromaDB returned candidates in
            # similarity-desc order, so neutral (all-zero) weights make the
            # composite equal to similarity and preserve semantic-only order.
            scored.sort(key=lambda t: t[1], reverse=True)
            dense_episodes = [ep for ep, _ in scored[:k]]
        else:
            dense_episodes = episodes

        # AD-979c: optional hybrid fusion with the FTS5 sparse axis. Off by
        # default and a no-op when the sparse axis returns nothing, so the
        # dense order is byte-identical unless a keyword hit actually adds/raises
        # an episode. The confidence signal above is intentionally left as the
        # DENSE Feeling-of-Knowing (AD-979a) — hybrid changes WHICH episodes are
        # returned, not how confident the cosine recall was.
        if self._hybrid_recall_enabled and self._fts_db is not None:
            dense_episodes = await self._fuse_dense_sparse(query, dense_episodes, k)

        return dense_episodes, confidence

    async def _fuse_dense_sparse(
        self, query: str, dense_episodes: list[Episode], k: int
    ) -> list[Episode]:
        """AD-979c: fuse the dense episode ranking with the FTS5 keyword ranking.

        The dense list (already threshold-filtered + ordered) is the cosine
        ranking; ``keyword_search`` over an OR-of-keywords query is the sparse
        ranking. :func:`reciprocal_rank_fusion` unions them so a
        vocabulary-mismatched episode present only in the sparse ranking is
        surfaced, while a confident dense hit not matched by keyword is retained.
        Sparse-only ids are hydrated via ``get_by_ids``. Tier-2 honest-degrade:
        an empty/failed sparse axis returns the dense list unchanged
        (byte-identical to AD-979a recall).
        """
        try:
            match_query = fts_or_query(query)
            if not match_query:
                return dense_episodes
            sparse_hits = await self.keyword_search(match_query, k=k * 3)
            sparse_ids = [eid for eid, _rank in sparse_hits]
            if not sparse_ids:
                return dense_episodes
            dense_ids = [e.id for e in dense_episodes]
            fused = reciprocal_rank_fusion(
                [dense_ids, sparse_ids], k=self._hybrid_rrf_k
            )
            fused_ids = [eid for eid, _score in fused][:k]
            # Reuse the dense Episodes we already have; hydrate sparse-only ids.
            have: dict[str, Episode] = {e.id: e for e in dense_episodes}
            missing = [eid for eid in fused_ids if eid not in have]
            if missing:
                for ep in await self.get_by_ids(missing):
                    have[ep.id] = ep
            return [have[eid] for eid in fused_ids if eid in have]
        except Exception:
            logger.debug(
                "AD-979c: hybrid fusion failed; returning dense recall", exc_info=True,
            )
            return dense_episodes

    async def recall_with_control(
        self, query: str, k: int = 5, *, max_expansions: int = 1,
    ) -> tuple[list[Episode], RecallConfidence, list[str]]:
        """AD-979b: recall with a bounded metacognitive control loop.

        Nelson & Narens (1990): the monitor signal drives a control action.
        First a normal :meth:`recall_with_confidence` (the monitor). Then
        :func:`decide_recall_control` maps the band to an action:

          * ``accept`` (strong) / ``abstain`` (none) -> return immediately, NO
            extra work — zero cost on the happy path and on genuine absence.
          * ``expand`` (weak — the invisible miss) -> issue at most
            ``max_expansions`` reformulated/expanded re-queries
            (:func:`recall_expansion_variants`); adopt a variant's result only
            when it is strictly MORE accessible (higher best similarity), and
            stop early once a variant reaches ``strong``.

        Returns ``(episodes, confidence, actions)`` where ``actions`` is the
        audit trail (e.g. ``["expand", "requery:weak", "requery:strong"]``) so
        the caller can report honestly (AD-592): a still-``weak``/``none`` final
        band means "I looked, expanded, and remain uncertain" — never a
        fabricated answer. The returned confidence is the BEST one found.
        """
        episodes, confidence = await self.recall_with_confidence(query, k)
        action = decide_recall_control(confidence.band)
        actions: list[str] = [action]
        if action != "expand" or max_expansions <= 0:
            return episodes, confidence, actions

        for variant in recall_expansion_variants(query, max_n=max_expansions):
            v_eps, v_conf = await self.recall_with_confidence(variant, k)
            actions.append(f"requery:{v_conf.band}")
            if v_conf.best_similarity > confidence.best_similarity:
                episodes, confidence = v_eps, v_conf
            if confidence.band == "strong":
                break
        return episodes, confidence, actions

    async def retrieve_contrastive_episodes(
        self, query: str, k: int = 2,
    ) -> list[Episode]:
        """AD-655: return mid-band-similarity episodes (NOT top-k).

        Definition: episodes whose semantic similarity to the query is in
        the [0.4, 0.65] band -- relevant enough to be on-topic, distant
        enough to potentially carry contrasting outcome signal. Band
        thresholds are v1 defaults; AD-655b will introduce a Pydantic
        config knob.
        """
        if not self._collection:
            return []
        if not query.strip():
            return []
        count = self._collection.count()
        if count == 0:
            return []

        n_results = min(k * 5, count)
        result = self._collection.query(
            query_texts=[query],
            n_results=n_results,
            include=["metadatas", "documents", "distances"],
        )
        if not result or not result["ids"] or not result["ids"][0]:
            return []

        # AD-655 mid-band thresholds (similarity = 1 - distance)
        _MID_BAND_LOW = 0.4
        _MID_BAND_HIGH = 0.65

        contrastive: list[Episode] = []
        for i, doc_id in enumerate(result["ids"][0]):
            distance = result["distances"][0][i] if result["distances"] else 0.0
            similarity = 1.0 - distance
            if not (_MID_BAND_LOW <= similarity <= _MID_BAND_HIGH):
                continue
            metadata = result["metadatas"][0][i] if result["metadatas"] else {}
            document = result["documents"][0][i] if result["documents"] else ""
            ep = self._metadata_to_episode(doc_id, document, metadata)
            contrastive.append(ep)
            if len(contrastive) >= k:
                break

        # AD-655: emit CONTRASTIVE_RECALL when an emit hook is wired
        emit = getattr(self, "_emit_event", None)
        if emit is not None and contrastive:
            try:
                from probos.events import EventType
                emit(
                    EventType.CONTRASTIVE_RECALL,
                    {
                        "query_len": len(query),
                        "episode_ids": [ep.id for ep in contrastive],
                    },
                )
            except Exception:
                logger.debug("AD-655: CONTRASTIVE_RECALL emit failed", exc_info=True)
        return contrastive

    async def recall_by_anchor_scored(
        self,
        *,
        agent_id: str = "",
        department: str = "",
        channel: str = "",
        trigger_type: str = "",
        trigger_agent: str = "",
        watch_section: str = "",
        participants: list[str] | None = None,
        time_range: tuple[float, float] | None = None,
        semantic_query: str = "",
        limit: int = 50,
        trust_network: Any = None,
        hebbian_router: Any = None,
        intent_type: str = "",
        weights: dict[str, float] | None = None,
        convergence_bonus: float = 0.10,
        query_watch_section: str = "",
        temporal_match_weight: float = 0.10,
        temporal_mismatch_penalty: float = 0.15,
        anchor_bonus: float = 0.08,
    ) -> list[RecallScore]:
        """AD-603: Anchor recall with full composite scoring."""
        raw_episodes = await self.recall_by_anchor(
            department=department,
            channel=channel,
            trigger_type=trigger_type,
            trigger_agent=trigger_agent,
            watch_section=watch_section,
            agent_id=agent_id,
            participants=participants,
            time_range=time_range,
            semantic_query=semantic_query,
            limit=limit,
        )

        if not raw_episodes:
            return []

        ep_similarities: dict[str, float] = {}
        collection = getattr(self, "_collection", None)
        if semantic_query and collection:
            try:
                count = collection.count()
                if count > 0:
                    from probos.knowledge.embeddings import reformulate_query

                    query_variants = (
                        reformulate_query(semantic_query)
                        if getattr(self, "_query_reformulation_enabled", True)
                        else [semantic_query]
                    )
                    n_results = min(limit * 3, count)
                    result = collection.query(
                        query_texts=query_variants,
                        n_results=n_results,
                        include=["distances"],
                    )
                    if result and result.get("ids"):
                        distances = result.get("distances") or []
                        for query_index, ids_for_query in enumerate(result["ids"]):
                            for result_index, doc_id in enumerate(ids_for_query):
                                distance = (
                                    distances[query_index][result_index]
                                    if distances and query_index < len(distances)
                                    and result_index < len(distances[query_index])
                                    else 0.0
                                )
                                similarity = 1.0 - distance
                                if doc_id not in ep_similarities or similarity > ep_similarities[doc_id]:
                                    ep_similarities[doc_id] = similarity
            except Exception:
                logger.debug("AD-603: Semantic similarity lookup for anchor episodes failed", exc_info=True)

        keyword_map: dict[str, int] = {}
        if semantic_query:
            try:
                kw_results = await self.keyword_search(semantic_query, k=limit * 3)
                for ep_id, _rank in kw_results:
                    keyword_map[ep_id] = keyword_map.get(ep_id, 0) + 1
            except Exception:
                logger.debug("AD-603: Keyword search for anchor episodes failed", exc_info=True)

        now = time.time()
        results: list[RecallScore] = []
        for ep in raw_episodes:
            semantic_similarity = ep_similarities.get(ep.id, 0.0)

            trust_weight = 0.5
            if trust_network is not None and agent_id:
                try:
                    trust_weight = trust_network.get_score(agent_id)
                except Exception:
                    trust_weight = 0.5

            hebbian_weight = 0.5
            if hebbian_router is not None and intent_type:
                try:
                    hebbian_weight = hebbian_router.get_weight(intent_type, agent_id, rel_type="intent")
                except Exception:
                    hebbian_weight = 0.5

            age_hours = (now - ep.timestamp) / 3600.0 if ep.timestamp > 0 else 168.0 * 4
            recency_weight = math.exp(-age_hours / 168.0)
            keyword_hits = keyword_map.get(ep.id, 0)
            temporal_match = bool(
                query_watch_section
                and getattr(ep, "anchors", None)
                and getattr(ep.anchors, "watch_section", "") == query_watch_section
            )

            recall_score = self.score_recall(
                episode=ep,
                semantic_similarity=semantic_similarity,
                keyword_hits=keyword_hits,
                trust_weight=trust_weight,
                hebbian_weight=hebbian_weight,
                recency_weight=recency_weight,
                weights=weights,
                convergence_bonus=convergence_bonus,
                temporal_match=temporal_match,
                temporal_match_weight=temporal_match_weight,
                temporal_mismatch_penalty=temporal_mismatch_penalty,
                query_has_temporal_intent=bool(query_watch_section),
                importance=ep.importance,
                importance_weight=0.05,
            )
            results.append(
                RecallScore(
                    episode=recall_score.episode,
                    semantic_similarity=recall_score.semantic_similarity,
                    keyword_hits=recall_score.keyword_hits,
                    trust_weight=recall_score.trust_weight,
                    hebbian_weight=recall_score.hebbian_weight,
                    recency_weight=recall_score.recency_weight,
                    anchor_confidence=recall_score.anchor_confidence,
                    tcm_similarity=recall_score.tcm_similarity,
                    composite_score=recall_score.composite_score + max(0.0, anchor_bonus),
                )
            )

        results.sort(key=lambda result: result.composite_score, reverse=True)
        return results

    async def recall_for_agent(self, agent_id: str, query: str, k: int = 5) -> list[Episode]:
        """Recall episodes scoped to a specific agent. Sovereign memory — only this agent's experiences (AD-397).

        AD-981a: a thin byte-identical shim over
        :meth:`recall_for_agent_with_confidence` (the single source of truth for
        the sovereign query+filter path). Callers that want the agent-scoped
        Feeling-of-Knowing band call that method directly; this returns just the
        episodes, so every existing caller is unchanged.
        """
        episodes, _confidence = await self.recall_for_agent_with_confidence(
            agent_id, query, k
        )
        return episodes

    async def recall_for_agent_with_confidence(
        self, agent_id: str, query: str, k: int = 5
    ) -> tuple[list[Episode], RecallConfidence]:
        """AD-981a: sovereign agent recall PLUS the AD-979a agent-scoped
        Feeling-of-Knowing signal.

        Same sovereign query / relaxed-threshold / shard path as the historical
        ``recall_for_agent`` (which now delegates here, byte-identical), but it
        also surfaces the similarity distribution over THIS AGENT'S OWN
        candidates: the best agent-owned similarity and how many of the agent's
        episodes the query reached, classified into a ``strong``/``weak``/``none``
        band. Where :meth:`recall_with_confidence` measures GLOBAL accessibility,
        this answers "how accessible is *this agent's* memory for this query" —
        the right signal for the sovereign path and for recall calibration.

        The band is derived from the agent-owned distribution BEFORE the relaxed
        relevance cut (Koriat accessibility) and classified against the GENERAL
        ``relevance_threshold`` / ``weak_floor`` (not the relaxed agent-return
        threshold), so it is directly comparable to the global AD-979a band and
        the *invisible miss* (a relevant-ish owned memory under the confident-
        recall bar) becomes visible instead of silently dropped. When
        ``recall_fok_logging`` is enabled the band is logged per call, turning a
        live multi-agent session into a recall-calibration tool. The returned
        episode list is exactly what ``recall_for_agent`` returns.
        """
        _none = RecallConfidence(
            band="none", best_similarity=0.0, candidate_count=0, query=query[:200],
        )
        if not self._collection:
            return [], _none
        count = self._collection.count()
        if count == 0:
            return [], _none

        n_results = min(k * 5, count)
        result = self._collection.query(
            query_texts=[query],
            n_results=n_results,
            include=["metadatas", "documents", "distances"],
        )
        if not result or not result["ids"] or not result["ids"][0]:
            return [], _none

        # BF-027: relaxed threshold for agent-scoped recall. The sovereign shard
        # filter (agent_ids) already constrains results, and conversational
        # Captain queries ("what did you post?") are semantically distant from
        # stored episode text — 0.7 filters too aggressively.
        agent_recall_threshold = min(self.relevance_threshold, self._agent_recall_threshold)
        # AD-981a: agent-scoped Feeling-of-Knowing accumulators, tallied over the
        # agent's OWN candidates BEFORE the relevance cut so the invisible miss
        # (owned-but-sub-threshold) is captured. Read-only — never affects which
        # episodes are returned.
        agent_best_sim = 0.0
        agent_candidate_count = 0

        episodes: list[Episode] = []
        for i, doc_id in enumerate(result["ids"][0]):
            distance = result["distances"][0][i] if result["distances"] else 0.0
            similarity = 1.0 - distance
            metadata = result["metadatas"][0][i] if result["metadatas"] else {}

            # Sovereign shard filter — only this agent's memories.
            agent_ids_json = metadata.get("agent_ids_json", "[]")
            try:
                agent_ids = json.loads(agent_ids_json)
            except (json.JSONDecodeError, TypeError):
                agent_ids = []
            is_owned = agent_id in agent_ids

            # AD-981a: tally the agent-scoped accessibility distribution (owned
            # candidates, pre-threshold). Order of the threshold/shard filters
            # below is unchanged for the RETURNED set — both are pure `continue`
            # guards, so their intersection (and the k-cap) is identical.
            if is_owned:
                agent_candidate_count += 1
                if similarity > agent_best_sim:
                    agent_best_sim = similarity

            if similarity < agent_recall_threshold:
                continue
            if not is_owned:
                continue

            document = result["documents"][0][i] if result["documents"] else ""
            ep = self._metadata_to_episode(doc_id, document, metadata)
            # AD-541e: Content hash verification
            if self._verify_on_recall:
                stored_hash = metadata.get("content_hash", "")
                _verify_episode_hash(ep, stored_hash, metadata, self._collection)
            episodes.append(ep)
            if len(episodes) >= k:
                break

        confidence = RecallConfidence(
            band=classify_recall_confidence(
                agent_best_sim,
                agent_candidate_count,
                relevance_threshold=self.relevance_threshold,
                weak_floor=self._recall_confidence_weak_floor,
            ),
            best_similarity=agent_best_sim,
            candidate_count=agent_candidate_count,
            query=query[:200],
        )

        # AD-981a: surface the band as a calibration signal when enabled. Tier-2
        # — logging must never break recall.
        if self._recall_fok_logging:
            logger.info(
                "AD-981a recall FoK: agent=%s band=%s best_sim=%.3f "
                "owned_candidates=%d returned=%d query=%r",
                agent_id,
                confidence.band,
                confidence.best_similarity,
                confidence.candidate_count,
                len(episodes),
                query[:80],
            )

        # AD-567d: Record deliberate recall access for activation tracking
        if episodes and self._activation_tracker:
            try:
                await self._activation_tracker.record_batch_access(
                    [ep.id for ep in episodes], access_type="recall"
                )
            except Exception:
                logger.debug("AD-567d: Activation tracking failed", exc_info=True)

        return episodes, confidence

    async def recent_for_agent(self, agent_id: str, k: int = 5) -> list[Episode]:
        """BF-027: Return the k most recent episodes for a specific agent.

        Timestamp-based fallback when semantic recall returns nothing.
        No relevance threshold — just the most recent experiences.
        Does NOT record activation access (fallback scan, not deliberate recall).
        """
        if not self._collection:
            return []
        count = self._collection.count()
        if count == 0:
            return []

        result = self._collection.get(
            include=["metadatas", "documents"],
        )
        if not result or not result["ids"]:
            return []

        # Filter to this agent's sovereign shard, sort by timestamp
        agent_episodes: list[tuple[str, dict, str]] = []
        for i, doc_id in enumerate(result["ids"]):
            metadata = result["metadatas"][i] if result["metadatas"] else {}
            agent_ids_json = metadata.get("agent_ids_json", "[]")
            try:
                agent_ids = json.loads(agent_ids_json)
            except (json.JSONDecodeError, TypeError):
                agent_ids = []
            if agent_id in agent_ids:
                document = result["documents"][i] if result["documents"] else ""
                agent_episodes.append((doc_id, metadata, document))

        # Sort by timestamp descending (most recent first)
        agent_episodes.sort(key=lambda x: x[1].get("timestamp", 0), reverse=True)

        episodes: list[Episode] = []
        for doc_id, metadata, document in agent_episodes[:k]:
            ep = self._metadata_to_episode(doc_id, document, metadata)
            # AD-541e: Content hash verification
            if self._verify_on_recall:
                stored_hash = metadata.get("content_hash", "")
                _verify_episode_hash(ep, stored_hash, metadata, self._collection)
            episodes.append(ep)
        return episodes

    async def recall_by_intent(self, intent_type: str, k: int = 5) -> list[Episode]:
        """Filter by intent type, then rank by recency."""
        if not self._collection:
            return []

        # Use ChromaDB where filter on intent metadata
        count = self._collection.count()
        if count == 0:
            return []

        # Query with intent filter — get all matching, limited by k
        try:
            result = self._collection.get(
                where={"intent_type": intent_type},
                include=["metadatas", "documents"],
            )
        except Exception:
            logger.debug("Episodic memory operation failed", exc_info=True)
            # Fallback: get all and filter manually
            result = self._collection.get(include=["metadatas", "documents"])

        if not result or not result["ids"]:
            return []

        # Sort by timestamp descending (most recent first)
        paired = list(zip(result["ids"], result["metadatas"], result["documents"]))
        paired.sort(key=lambda x: x[1].get("timestamp", 0), reverse=True)

        episodes: list[Episode] = []
        for doc_id, metadata, document in paired[:k]:
            # Double-check intent filter for manual fallback
            if metadata.get("intent_type") != intent_type:
                continue
            ep = self._metadata_to_episode(doc_id, document, metadata)
            episodes.append(ep)
            if len(episodes) >= k:
                break

        return episodes

    async def recent(self, k: int = 10) -> list[Episode]:
        """Return the k most recent episodes."""
        if not self._collection:
            return []

        count = self._collection.count()
        if count == 0:
            return []

        result = self._collection.get(
            include=["metadatas", "documents"],
        )

        if not result or not result["ids"]:
            return []

        # Sort by timestamp descending
        paired = list(zip(result["ids"], result["metadatas"], result["documents"]))
        paired.sort(key=lambda x: x[1].get("timestamp", 0), reverse=True)

        return [
            self._metadata_to_episode(doc_id, document, metadata)
            for doc_id, metadata, document in paired[:k]
        ]

    async def get_embeddings(self, episode_ids: list[str]) -> dict[str, list[float]]:
        """Retrieve stored embeddings for the given episode IDs.

        Returns a dict mapping episode_id -> embedding vector.
        Episodes without embeddings (or if ChromaDB is unavailable) are omitted.
        Used by AD-531 episode clustering during dream cycles.
        """
        if not self._collection or not episode_ids:
            return {}

        try:
            result = self._collection.get(
                ids=episode_ids,
                include=["embeddings"],
            )
            if not result or not result["ids"] or result["embeddings"] is None:
                return {}

            embeddings: dict[str, list[float]] = {}
            for i, doc_id in enumerate(result["ids"]):
                emb = result["embeddings"][i]
                if emb is not None and len(emb) > 0:
                    embeddings[doc_id] = list(emb)
            return embeddings

        except Exception:
            logger.debug("Failed to retrieve embeddings", exc_info=True)
            return {}

    async def count_for_agent(self, agent_id: str) -> int:
        """BF-033: Return the total episode count for a specific agent."""
        if not self._collection:
            return 0
        count = self._collection.count()
        if count == 0:
            return 0
        result = self._collection.get(include=["metadatas"])
        if not result or not result["metadatas"]:
            return 0
        total = 0
        for metadata in result["metadatas"]:
            agent_ids_json = metadata.get("agent_ids_json", "[]")
            try:
                agent_ids = json.loads(agent_ids_json)
            except (json.JSONDecodeError, TypeError):
                agent_ids = []
            if agent_id in agent_ids:
                total += 1
        return total

    async def get_stats(self) -> dict[str, Any]:
        """Total episodes, intent distribution, average success rate, most-used agents."""
        if not self._collection:
            return {"total": 0}

        count = self._collection.count()
        if count == 0:
            return {"total": 0}

        result = self._collection.get(include=["metadatas"])
        if not result or not result["metadatas"]:
            return {"total": count}

        from collections import Counter
        intent_counts: Counter[str] = Counter()
        agent_counts: Counter[str] = Counter()
        success_total = 0
        outcome_total = 0

        for metadata in result["metadatas"]:
            outcomes = json.loads(metadata.get("outcomes_json", "[]"))
            agents = json.loads(metadata.get("agent_ids_json", "[]"))
            for o in outcomes:
                intent_counts[o.get("intent", "unknown")] += 1
                outcome_total += 1
                if o.get("success"):
                    success_total += 1
            for a in agents:
                agent_counts[a] += 1

        return {
            "total": count,
            "intent_distribution": dict(intent_counts.most_common(10)),
            "avg_success_rate": (
                success_total / outcome_total if outcome_total else 0.0
            ),
            "most_used_agents": dict(agent_counts.most_common(5)),
        }

    # ---- helpers --------------------------------------------------

    @staticmethod
    def _episode_to_metadata(ep: Episode) -> dict:
        """Convert an Episode to a ChromaDB-compatible metadata dict.

        ChromaDB metadata values must be str, int, float, or bool.
        Complex types are serialized to JSON strings.
        """
        # Extract primary intent type from outcomes
        intent_type = ""
        outcomes = ep.outcomes or []
        if outcomes:
            intent_type = outcomes[0].get("intent", "") if isinstance(outcomes[0], dict) else ""

        # Normalize timestamp before hashing — use the same value in both
        # Round to 6 decimal places (microsecond precision) — IEEE 754
        # double has ~15-16 significant digits; 10-digit epoch + 7 decimals
        # = 17 digits, which exceeds reliable precision and causes ChromaDB
        # (SQLite) to truncate, breaking the content hash on recall.
        ts = round(float(ep.timestamp or time.time()), 6)
        dur = float(ep.duration_ms)
        # Build normalized Episode for hashing so hash matches stored values
        from dataclasses import replace
        normalized = replace(ep, timestamp=ts, duration_ms=dur, source=ep.source or "direct", anchors=None)

        # AD-871: Resolve graded provenance (back-fill source_type from the
        # legacy source tag; derive confidence from source_type when graded).
        _source_type, _confidence = resolve_provenance(
            ep.source or "direct", ep.source_type, ep.confidence
        )

        metadata = {
            "timestamp": ts,
            "intent_type": intent_type,
            "dag_summary_json": json.dumps(ep.dag_summary),
            "outcomes_json": json.dumps(ep.outcomes),
            "reflection": ep.reflection or "",
            "agent_ids_json": json.dumps(ep.agent_ids),
            "duration_ms": dur,
            "shapley_values_json": json.dumps(ep.shapley_values),
            "trust_deltas_json": json.dumps(ep.trust_deltas),
            "source": ep.source or "direct",
            "anchors_json": json.dumps(dataclasses.asdict(ep.anchors)) if ep.anchors else "",
            "content_hash": compute_episode_hash(normalized),
            "user_input": ep.user_input or "",  # AD-605: preserve original for recall
            "_hash_v": 2,  # Hash normalization version (round(ts,6) + float coercion)
            "importance": int(ep.importance),  # AD-598: importance score (1-10)
            "valid_from": float(ep.valid_from),
            "valid_until": float(ep.valid_until),
            # AD-871: Provenance-aware memory envelope (graded belief)
            "source_type": _source_type,
            "confidence": float(_confidence),
            "verification_count": int(ep.verification_count),
            "contradicted_by_json": json.dumps(ep.contradicted_by or []),
            # AD-873: Ebbinghaus memory decay (strength derived from age+stability)
            "strength": float(ep.strength),
            "stability": float(ep.stability),
        }
        # AD-570: Promote key anchor fields for ChromaDB where-clause filtering
        if ep.anchors:
            metadata["anchor_department"] = ep.anchors.department or ""
            metadata["anchor_channel"] = ep.anchors.channel or ""
            metadata["anchor_trigger_type"] = ep.anchors.trigger_type or ""
            metadata["anchor_trigger_agent"] = ep.anchors.trigger_agent or ""
            metadata["anchor_watch_section"] = ep.anchors.watch_section or ""
        else:
            metadata["anchor_department"] = ""
            metadata["anchor_channel"] = ""
            metadata["anchor_trigger_type"] = ""
            metadata["anchor_trigger_agent"] = ""
            metadata["anchor_watch_section"] = ""
        return metadata

    @staticmethod
    def _prepare_document(episode: "Episode") -> str:
        """AD-584d: Build enriched document text for ChromaDB embedding.

        Concatenates anchor metadata, user_input, reflection, and heuristic
        question seeds into the document text. This aligns the embedding with
        FTS5 (which already indexes user_input + reflection) and adds
        elaborative encoding via question seeding (Craik & Tulving 1975).

        The output is embedding-only — never displayed to users or
        reconstructed back to Episode. Content order (anchors → user_input →
        reflection → questions) ensures structural context survives if the
        embedding model truncates long documents.
        """
        parts: list[str] = []

        # Structural context (AD-605)
        if episode.anchors:
            if episode.anchors.department:
                parts.append(f"[{episode.anchors.department}]")
            if episode.anchors.channel:
                parts.append(f"[{episode.anchors.channel}]")
            if episode.anchors.watch_section:
                parts.append(f"[{episode.anchors.watch_section}]")
            if episode.anchors.trigger_type:
                parts.append(f"[{episode.anchors.trigger_type}]")

        # Core content — user_input + reflection (AD-584d)
        if episode.user_input:
            parts.append(episode.user_input)
        if episode.reflection:
            parts.append(episode.reflection)

        # Question seeds — heuristic elaborative encoding (AD-584d)
        questions = EpisodicMemory._generate_question_seeds(episode)
        if questions:
            parts.append("[Questions: " + " | ".join(questions) + "]")

        return " ".join(parts)

    @staticmethod
    def _generate_question_seeds(episode: "Episode") -> list[str]:
        """AD-584d: Generate heuristic questions this episode could answer.

        Elaborative encoding — deeper processing at write time improves
        retrieval at recall time. Questions bridge the Q→A gap so that
        query-like recall prompts have direct semantic overlap with the
        stored document.

        Returns 0-3 questions based on available metadata. No LLM call.

        Note: Reflection content is NOT templated into questions — it's
        already in the embedding via Section 1, and templating it produces
        grammatically broken questions that hurt embedding quality.
        """
        questions: list[str] = []

        # Intent-based question
        intent_type = ""
        if episode.dag_summary:
            intent_type = episode.dag_summary.get("intent", "") or episode.dag_summary.get("intent_type", "")
        if intent_type:
            questions.append(f"What happened when {intent_type} was executed?")

        # Outcome-based question (references specific result, not intent)
        if episode.outcomes:
            first_result = episode.outcomes[0].get("result", "")
            if first_result:
                questions.append(f"What was the outcome of {first_result}?")

        # Department-based question (if no intent question generated)
        if not intent_type and episode.anchors and episode.anchors.department:
            questions.append(f"What did {episode.anchors.department} observe?")

        return questions[:3]  # Cap at 3

    @staticmethod
    def _metadata_to_episode(
        doc_id: str, document: str, metadata: dict
    ) -> Episode:
        """Convert ChromaDB result back to an Episode."""
        anchors_raw = metadata.get("anchors_json", "")
        anchors = AnchorFrame(**json.loads(anchors_raw)) if anchors_raw else None
        # AD-871: Decode provenance envelope with honest-degrade fallbacks.
        # Pre-AD-871 episodes lack these keys → safe defaults (empty
        # source_type, confidence 1.0, 0 verifications, no contradictions).
        source_type = metadata.get("source_type", "") or ""
        try:
            confidence = float(metadata.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        try:
            verification_count = int(metadata.get("verification_count", 0))
        except (TypeError, ValueError):
            verification_count = 0
        contradicted_raw = metadata.get("contradicted_by_json", "")
        try:
            contradicted_by = json.loads(contradicted_raw) if contradicted_raw else []
            if not isinstance(contradicted_by, list):
                contradicted_by = []
        except (json.JSONDecodeError, TypeError):
            contradicted_by = []
        # AD-873: Ebbinghaus decay fields (pre-AD-873 episodes default cleanly).
        try:
            strength = float(metadata.get("strength", 1.0))
        except (TypeError, ValueError):
            strength = 1.0
        try:
            stability = float(metadata.get("stability", EBBINGHAUS_DEFAULT_STABILITY_SECONDS))
        except (TypeError, ValueError):
            stability = EBBINGHAUS_DEFAULT_STABILITY_SECONDS
        return Episode(
            id=doc_id,
            timestamp=round(float(metadata.get("timestamp", 0.0)), 6),
            user_input=metadata.get("user_input", document),  # AD-605: prefer stored original
            dag_summary=json.loads(metadata.get("dag_summary_json", "{}")),
            outcomes=json.loads(metadata.get("outcomes_json", "[]")),
            reflection=metadata.get("reflection", None) or None,
            agent_ids=json.loads(metadata.get("agent_ids_json", "[]")),
            duration_ms=float(metadata.get("duration_ms", 0.0)),
            embedding=[],  # ChromaDB manages embeddings internally
            shapley_values=json.loads(metadata.get("shapley_values_json", "{}")),
            trust_deltas=json.loads(metadata.get("trust_deltas_json", "[]")),
            source=metadata.get("source", "direct"),
            anchors=anchors,
            importance=int(metadata.get("importance", 5)),
            valid_from=float(metadata.get("valid_from", 0.0)),
            valid_until=float(metadata.get("valid_until", 0.0)),
            # AD-871: Provenance-aware memory envelope
            source_type=source_type,
            confidence=confidence,
            verification_count=verification_count,
            contradicted_by=contradicted_by,
            # AD-873: Ebbinghaus memory decay
            strength=strength,
            stability=stability,
        )

    # ---- AD-567b: Salience-weighted recall pipeline --------------------

    async def keyword_search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        """FTS5 keyword search. Returns [(episode_id, rank_score), ...].

        AD-567b: Secondary retrieval channel alongside ChromaDB vector search.
        """
        if self._fts_db is None or not query.strip():
            return []
        try:
            cursor = await self._fts_db.execute(
                "SELECT episode_id, rank FROM episode_fts WHERE episode_fts MATCH ? ORDER BY rank LIMIT ?",
                (query, k),
            )
            rows = await cursor.fetchall()
            return [(row[0], float(row[1])) for row in rows]
        except Exception:
            logger.debug("AD-567b: FTS5 keyword search failed", exc_info=True)
            return []

    async def recall_for_agent_scored(
        self, agent_id: str, query: str, k: int = 5,
    ) -> list[tuple[Episode, float]]:
        """Like recall_for_agent but returns (episode, similarity) tuples.

        AD-567b: Exposes cosine similarity scores for composite re-ranking.
        AD-584: Embeds query variants (original + reformulated) and takes
        the best (lowest distance) per episode for Q->A bridging.
        """
        if not self._collection:
            return []
        count = self._collection.count()
        if count == 0:
            return []

        # AD-584: Query reformulation — embed original + declarative template
        from probos.knowledge.embeddings import reformulate_query
        query_variants = reformulate_query(query) if self._query_reformulation_enabled else [query]

        n_results = min(k * 5, count)
        result = self._collection.query(
            query_texts=query_variants,
            n_results=n_results,
            include=["metadatas", "documents", "distances"],
        )
        if not result or not result["ids"]:
            return []

        # AD-584: Merge results across query variants — keep best (lowest) distance per episode
        best_distance: dict[str, float] = {}
        best_meta: dict[str, dict] = {}
        best_doc: dict[str, str] = {}
        for q_idx in range(len(result["ids"])):
            if not result["ids"][q_idx]:
                continue
            for i, doc_id in enumerate(result["ids"][q_idx]):
                distance = result["distances"][q_idx][i] if result["distances"] else 0.0
                if doc_id not in best_distance or distance < best_distance[doc_id]:
                    best_distance[doc_id] = distance
                    best_meta[doc_id] = result["metadatas"][q_idx][i] if result["metadatas"] else {}
                    best_doc[doc_id] = result["documents"][q_idx][i] if result["documents"] else ""

        scored: list[tuple[Episode, float]] = []
        agent_recall_threshold = min(self.relevance_threshold, self._agent_recall_threshold)

        # Sort by distance ascending (best matches first)
        for doc_id, distance in sorted(best_distance.items(), key=lambda x: x[1]):
            similarity = 1.0 - distance
            if similarity < agent_recall_threshold:
                continue
            metadata = best_meta[doc_id]
            agent_ids_json = metadata.get("agent_ids_json", "[]")
            try:
                agent_ids = json.loads(agent_ids_json)
            except (json.JSONDecodeError, TypeError):
                agent_ids = []
            if agent_id not in agent_ids:
                continue
            document = best_doc[doc_id]
            ep = self._metadata_to_episode(doc_id, document, metadata)
            if self._verify_on_recall:
                stored_hash = metadata.get("content_hash", "")
                _verify_episode_hash(ep, stored_hash, metadata, self._collection)
            scored.append((ep, similarity))
            if len(scored) >= k:
                break

        # AD-567d: Record deliberate recall access for activation tracking
        if scored and self._activation_tracker:
            try:
                await self._activation_tracker.record_batch_access(
                    [ep.id for ep, _ in scored], access_type="recall"
                )
            except Exception:
                logger.debug("AD-567d: Activation tracking failed", exc_info=True)

        return scored

    @staticmethod
    def score_recall(
        episode: Episode,
        semantic_similarity: float,
        keyword_hits: int = 0,
        trust_weight: float = 0.5,
        hebbian_weight: float = 0.5,
        recency_weight: float = 0.0,
        weights: dict[str, float] | None = None,
        convergence_bonus: float = 0.10,
        temporal_match: bool = False,          # BF-147: query temporal cue matches episode anchor
        temporal_match_weight: float = 0.10,   # BF-147: bonus when temporal cue matches
        temporal_mismatch_penalty: float = 0.15,  # BF-155: penalty when query watch differs from episode watch
        query_has_temporal_intent: bool = False,   # BF-155: True when query_watch_section is non-empty
        importance: int = 5,               # AD-598: episode importance (1-10)
        importance_weight: float = 0.0,    # AD-598: weight in composite (0.0 = disabled)
        tcm_similarity: float = 0.0,       # AD-601: TCM temporal context similarity (0.0–1.0)
        tcm_weight: float = 0.0,           # AD-601: weight in composite (0.0 = disabled)
        tcm_fallback_watch_weight: float = 0.05,  # AD-601: residual watch_section weight when TCM active
    ) -> RecallScore:
        """Compute composite salience score for a recalled episode (AD-567b/c, AD-584c).

        Weights default to the AD-584c rebalanced formula:
          0.35*semantic + 0.20*keyword + 0.10*trust + 0.05*hebbian + 0.15*recency + 0.15*anchor
        AD-567c: anchor_confidence uses Johnson-weighted dimension scoring.
        AD-584c: convergence bonus (+0.10 default) for episodes found by both
        semantic AND keyword channels (spreading activation).
        """
        from probos.cognitive.anchor_quality import compute_anchor_confidence

        w = weights or {
            "semantic": 0.35, "keyword": 0.20, "trust": 0.10,
            "hebbian": 0.05, "recency": 0.15, "anchor": 0.15,
        }

        # AD-567c: Johnson-weighted anchor confidence (replaces simple field count)
        anchor_confidence = compute_anchor_confidence(episode.anchors)

        keyword_norm = min(keyword_hits / 3.0, 1.0) if keyword_hits > 0 else 0.0

        composite = (
            w.get("semantic", 0.35) * semantic_similarity
            + w.get("keyword", 0.20) * keyword_norm
            + w.get("trust", 0.10) * trust_weight
            + w.get("hebbian", 0.05) * hebbian_weight
            + w.get("recency", 0.15) * recency_weight
            + w.get("anchor", 0.15) * anchor_confidence
        )

        # AD-598: Importance contribution — normalized 1-10 to 0.0-1.0
        if importance_weight > 0:
            importance_norm = (max(1, min(10, importance)) - 1) / 9.0
            composite += importance_weight * importance_norm

        # AD-584c: Convergence bonus — multi-pathway evidence accumulation.
        # Episodes found by BOTH semantic AND keyword channels get a bonus.
        if semantic_similarity > 0.0 and keyword_hits > 0:
            composite += max(0.0, convergence_bonus)

        # AD-601: TCM temporal context gradient (replaces binary watch_section matching)
        if tcm_weight > 0.0 and tcm_similarity > 0.0:
            # TCM provides smooth temporal proximity — primary temporal signal
            composite += tcm_weight * tcm_similarity
            # Residual watch_section match — small discrete bonus on top of TCM
            if temporal_match:
                composite += max(0.0, tcm_fallback_watch_weight)
        else:
            # Fallback: no TCM vector available (legacy episodes) — use original BF-147/BF-155 logic
            if temporal_match:
                composite += max(0.0, temporal_match_weight)
            elif query_has_temporal_intent and not temporal_match:
                _ep_watch = (
                    getattr(episode, "anchors", None)
                    and getattr(episode.anchors, "watch_section", "")
                )
                if _ep_watch:
                    composite -= min(temporal_mismatch_penalty, composite)

        return RecallScore(
            episode=episode,
            semantic_similarity=semantic_similarity,
            keyword_hits=keyword_hits,
            trust_weight=trust_weight,
            hebbian_weight=hebbian_weight,
            recency_weight=recency_weight,
            anchor_confidence=anchor_confidence,
            tcm_similarity=tcm_similarity,
            composite_score=composite,
        )

    async def recall_weighted(
        self,
        agent_id: str,
        query: str,
        *,
        trust_network: Any = None,
        hebbian_router: Any = None,
        intent_type: str = "",
        k: int = 5,
        context_budget: int = 4000,
        weights: dict[str, float] | None = None,
        anchor_confidence_gate: float = 0.0,
        composite_score_floor: float = 0.0,
        max_recall_episodes: int = 0,
        recall_quality_floor: float = 0.0,
        convergence_bonus: float = 0.10,
        query_watch_section: str = "",           # BF-147: temporal cue from query
        temporal_match_weight: float = 0.10,     # BF-147: bonus when temporal cue matches
        temporal_mismatch_penalty: float = 0.15,  # BF-155: penalty for temporal contradiction
        valid_at: float = 0.0,  # AD-579b: when non-zero, exclude expired episodes
    ) -> list[RecallScore]:
        """Salience-weighted recall combining semantic + keyword + trust + Hebbian + recency + anchor (AD-567b/c).

        Over-fetches from ChromaDB, merges FTS5 keyword hits, scores each
        candidate with ``score_recall()``, and enforces context budget.
        AD-567c: applies RPMS confidence gating — episodes below anchor_confidence_gate
        are filtered from results (still accessible via recall_for_agent).
        AD-590: applies composite score floor — episodes below composite_score_floor
        are filtered from results after scoring, reducing noise from marginal candidates.
        AD-591: quality-aware budget enforcement — stops adding episodes when the
        next one would drop mean composite below recall_quality_floor, and enforces
        max_recall_episodes hard cap. 0 = disabled (backward compatible).
        """
        # 1. Semantic retrieval — over-fetch for re-ranking headroom
        scored_eps = await self.recall_for_agent_scored(agent_id, query, k=k * 3)
        ep_map: dict[str, tuple[Episode, float]] = {
            ep.id: (ep, sim) for ep, sim in scored_eps
        }
        # AD-601: Batch-fetch metadata for TCM vector access (single ChromaDB round-trip).
        # Avoids N+1 queries inside the scoring loop.
        _meta_by_id: dict[str, dict] = {}
        if getattr(self, '_tcm', None) is not None:
            try:
                _all_ids = list(ep_map.keys())
                _bulk = self._collection.get(ids=_all_ids, include=["metadatas"])
                if _bulk and _bulk["ids"] and _bulk["metadatas"]:
                    _meta_by_id = {
                        _bulk["ids"][i]: _bulk["metadatas"][i] or {}
                        for i in range(len(_bulk["ids"]))
                    }
            except Exception:
                logger.debug("AD-601: Batch metadata fetch failed", exc_info=True)

        # 2. Keyword retrieval — merge any new episodes
        keyword_map: dict[str, int] = {}
        kw_results = await self.keyword_search(query, k=k * 3)
        for ep_id, _rank in kw_results:
            # Count keyword hits per episode
            keyword_map[ep_id] = keyword_map.get(ep_id, 0) + 1
            if ep_id not in ep_map:
                # Fetch this episode from ChromaDB
                try:
                    result = self._collection.get(ids=[ep_id], include=["metadatas", "documents"])
                    if result and result["ids"]:
                        metadata = result["metadatas"][0] if result["metadatas"] else {}
                        # Sovereign shard filter
                        agent_ids_json = metadata.get("agent_ids_json", "[]")
                        try:
                            agent_ids = json.loads(agent_ids_json)
                        except (json.JSONDecodeError, TypeError):
                            agent_ids = []
                        if agent_id in agent_ids:
                            document = result["documents"][0] if result["documents"] else ""
                            ep = self._metadata_to_episode(ep_id, document, metadata)
                            ep_map[ep_id] = (ep, self._fts_keyword_floor)  # BF-134: keyword presence implies baseline relevance
                except Exception:
                    pass

        # 3. Score each candidate
        now = time.time()
        results: list[RecallScore] = []
        for ep_id, (ep, sim) in ep_map.items():
            # Trust weight
            tw = 0.5
            if trust_network is not None:
                try:
                    tw = trust_network.get_score(agent_id)
                except Exception:
                    tw = 0.5

            # Hebbian weight
            hw = 0.5
            if hebbian_router is not None and intent_type:
                try:
                    hw = hebbian_router.get_weight(intent_type, agent_id, rel_type="intent")
                except Exception:
                    hw = 0.5

            # Recency weight: exp(-age_hours / 168)
            age_hours = (now - ep.timestamp) / 3600.0 if ep.timestamp > 0 else 168.0 * 4
            rw = math.exp(-age_hours / 168.0)

            kw_hits = keyword_map.get(ep_id, 0)

            # BF-147: check temporal match between query and episode anchor
            _temporal_match = bool(
                query_watch_section
                and getattr(ep, "anchors", None)
                and getattr(ep.anchors, "watch_section", "") == query_watch_section
            )

            # AD-601: TCM temporal context similarity
            _tcm_sim = 0.0
            _tcm_wt = 0.0
            _tcm_fallback_watch_wt = 0.05
            if getattr(self, '_tcm', None) is not None:
                _tcm_wt = getattr(self, '_tcm_weight', 0.0)
                _tcm_fallback_watch_wt = getattr(self, '_tcm_fallback_watch_weight', 0.05)
                # Get stored TCM vector from pre-fetched metadata
                _ep_meta = _meta_by_id.get(ep_id, {})
                _tcm_raw = _ep_meta.get("tcm_vector_json", "")
                if _tcm_raw:
                    _stored_vec = deserialize_tcm_vector(_tcm_raw)
                    if _stored_vec:
                        _tcm_sim = self._tcm.compute_similarity(_stored_vec)

            rs = self.score_recall(
                episode=ep,
                semantic_similarity=sim,
                keyword_hits=kw_hits,
                trust_weight=tw,
                hebbian_weight=hw,
                recency_weight=rw,
                weights=weights,
                convergence_bonus=convergence_bonus,
                temporal_match=_temporal_match,
                temporal_match_weight=temporal_match_weight,
                temporal_mismatch_penalty=temporal_mismatch_penalty,      # BF-155
                query_has_temporal_intent=bool(query_watch_section),       # BF-155
                importance=ep.importance,       # AD-598
                importance_weight=0.05,         # AD-598: modest tiebreaker
                tcm_similarity=_tcm_sim,
                tcm_weight=_tcm_wt,
                tcm_fallback_watch_weight=_tcm_fallback_watch_wt,
            )
            results.append(rs)

        # AD-579b: Temporal validity filtering
        if valid_at > 0:
            results = [
                rs for rs in results
                if _episode_validity_check(rs.episode, valid_at)
            ]

        # 3b. AD-567c: RPMS confidence gating — filter low-confidence episodes
        if anchor_confidence_gate > 0.0:
            results = [rs for rs in results if rs.anchor_confidence >= anchor_confidence_gate]

        # 3c. AD-590: Composite score floor — filter marginal episodes
        if composite_score_floor > 0.0:
            results = [rs for rs in results if rs.composite_score >= composite_score_floor]

        # 4. Sort by composite score descending
        results.sort(key=lambda r: r.composite_score, reverse=True)

        # 5. Budget enforcement — quality-aware (AD-591)
        # Three stop conditions: (a) character budget, (b) max episodes, (c) quality degradation
        _effective_max = max_recall_episodes if max_recall_episodes > 0 else k * 2
        budgeted: list[RecallScore] = []
        total_chars = 0
        _running_score_sum = 0.0
        for rs in results:
            char_len = len(rs.episode.user_input) if rs.episode.user_input else 0

            # (a) Character budget
            if total_chars + char_len > context_budget and budgeted:
                break

            # (b) AD-591: Max episodes cap
            if len(budgeted) >= _effective_max:
                break

            # (c) AD-591: Quality degradation stop
            if recall_quality_floor > 0.0 and budgeted:
                _new_mean = (_running_score_sum + rs.composite_score) / (len(budgeted) + 1)
                if _new_mean < recall_quality_floor:
                    break

            budgeted.append(rs)
            total_chars += char_len
            _running_score_sum += rs.composite_score

        # AD-567d: Record deliberate recall access for activation tracking
        if budgeted and self._activation_tracker:
            try:
                await self._activation_tracker.record_batch_access(
                    [rs.episode.id for rs in budgeted], access_type="recall"
                )
            except Exception:
                logger.debug("AD-567d: Activation tracking failed", exc_info=True)

        # AD-607a/c: anchor-aware recall anomaly gate over scored results
        if getattr(self, "_security_config", None) is not None and budgeted:
            _aq = _AnchorQueryView(
                watch_section=query_watch_section or watch_section,
                channel=channel,
                department=department,
                trigger_agent=trigger_agent or agent_id,
                trigger_type=intent_type or trigger_type,
            )
            filtered_rs: list[RecallScore] = []
            for rs in budgeted:
                if self._security_anomaly_drop(
                    rs.episode, query=semantic_query, anchor_query=_aq,
                ):
                    continue
                filtered_rs.append(rs)
            budgeted = filtered_rs

        return budgeted

    async def recall_valid_at(
        self,
        timestamp: float,
        agent_id: str,
        query: str,
        **kwargs: Any,
    ) -> list[RecallScore]:
        """AD-579b: Recall weighted memories valid at a specific timestamp."""
        return await self.recall_weighted(
            agent_id,
            query,
            valid_at=timestamp,
            **kwargs,
        )

    # ---- AD-570: Anchor-indexed recall ------------------------------------

    async def recall_by_anchor(
        self,
        *,
        department: str = "",
        channel: str = "",
        trigger_type: str = "",
        trigger_agent: str = "",
        watch_section: str = "",
        agent_id: str = "",
        participants: list[str] | None = None,
        time_range: tuple[float, float] | None = None,
        semantic_query: str = "",
        limit: int = 50,
    ) -> list[Episode]:
        """AD-570: Structured anchor-field recall with optional semantic re-ranking.

        Two retrieval modes:
        1. **Enumeration** (no semantic_query): Uses ChromaDB .get() with where
           filters. Returns ALL matching episodes up to limit. No embedding needed.
        2. **Top-k with re-ranking** (semantic_query provided): Uses ChromaDB
           .query() with where filters + semantic similarity. Returns top-k
           matches that satisfy BOTH structural constraints and semantic relevance.

        Args:
            department: Filter by anchor_department (exact match).
            channel: Filter by anchor_channel (exact match).
            trigger_type: Filter by anchor_trigger_type (exact match).
            trigger_agent: Filter by anchor_trigger_agent (exact match).
            agent_id: Filter by agent_ids_json (post-retrieval Python filter).
            participants: AD-570b: Filter by episode participants (callsigns).
                If provided and participant_index is available, pre-filters
                episode IDs via the sidecar index.
            time_range: Filter by timestamp range (start, end) inclusive.
            semantic_query: If provided, uses .query() for semantic re-ranking.
                If empty, uses .get() for pure structured enumeration.
            limit: Max results to return.

        Returns:
            List of Episode objects matching the filters, sorted by:
            - Semantic similarity (descending) if semantic_query provided
            - Timestamp (descending) if enumeration mode
        """
        if not self._collection:
            return []

        # AD-570b: Pre-filter by participant using sidecar index
        candidate_ids: list[str] | None = None
        if participants and self._participant_index:
            try:
                candidate_ids = await self._participant_index.get_episode_ids_for_participants(
                    participants, require_all=True,
                )
                if not candidate_ids:
                    return []  # No episodes match the participant filter
            except Exception:
                logger.debug("AD-570b: Participant index query failed, falling back", exc_info=True)
                candidate_ids = None

        # Build ChromaDB where filter from non-empty params
        conditions: list[dict] = []
        if department:
            conditions.append({"anchor_department": department})
        if channel:
            conditions.append({"anchor_channel": channel})
        if trigger_type:
            conditions.append({"anchor_trigger_type": trigger_type})
        if trigger_agent:
            conditions.append({"anchor_trigger_agent": trigger_agent})
        if watch_section:
            conditions.append({"anchor_watch_section": watch_section})
        if time_range:
            conditions.append({"timestamp": {"$gte": time_range[0]}})
            conditions.append({"timestamp": {"$lte": time_range[1]}})

        where: dict | None = None
        if len(conditions) == 1:
            where = conditions[0]
        elif len(conditions) > 1:
            where = {"$and": conditions}

        # No filters + no query + no participant pre-filter = refuse to dump entire collection
        if not where and not semantic_query and candidate_ids is None:
            return []

        episodes: list[Episode] = []

        if not semantic_query:
            # Mode 1: Enumeration — use .get() with where filters
            try:
                get_kwargs: dict[str, Any] = {"include": ["metadatas", "documents"]}
                if candidate_ids is not None:
                    get_kwargs["ids"] = candidate_ids
                if where:
                    get_kwargs["where"] = where
                result = self._collection.get(**get_kwargs)
            except Exception:
                logger.debug("AD-570: recall_by_anchor enumeration failed", exc_info=True)
                return []

            if not result or not result.get("ids"):
                return []

            for i, doc_id in enumerate(result["ids"]):
                metadata = result["metadatas"][i] if result.get("metadatas") and i < len(result["metadatas"]) else {}
                document = result["documents"][i] if result.get("documents") and i < len(result["documents"]) else ""
                # Post-retrieval agent_id filter
                if agent_id:
                    agent_ids_json = metadata.get("agent_ids_json", "[]")
                    try:
                        agent_ids = json.loads(agent_ids_json)
                    except (json.JSONDecodeError, TypeError):
                        agent_ids = []
                    if agent_id not in agent_ids:
                        continue
                ep = self._metadata_to_episode(doc_id, document, metadata)
                if self._verify_on_recall:
                    stored_hash = metadata.get("content_hash", "")
                    _verify_episode_hash(ep, stored_hash, metadata, self._collection)
                episodes.append(ep)

            # Sort by timestamp descending
            episodes.sort(key=lambda e: e.timestamp, reverse=True)
            episodes = episodes[:limit]
        else:
            # Mode 2: Top-k with semantic re-ranking
            count = self._collection.count()
            if count == 0:
                return []

            n_results = min(limit * 3, count)
            kwargs: dict[str, Any] = {
                "query_texts": [semantic_query],
                "n_results": n_results,
                "include": ["metadatas", "documents", "distances"],
            }
            if where:
                kwargs["where"] = where

            try:
                result = self._collection.query(**kwargs)
            except Exception:
                logger.debug("AD-570: recall_by_anchor semantic query failed", exc_info=True)
                return []

            if not result or not result.get("ids") or not result["ids"][0]:
                return []

            candidate_set = set(candidate_ids) if candidate_ids is not None else None
            for i, doc_id in enumerate(result["ids"][0]):
                # AD-570b: Post-filter by participant index candidate_ids
                if candidate_set is not None and doc_id not in candidate_set:
                    continue
                metadata = result["metadatas"][0][i] if result.get("metadatas") and result["metadatas"] else {}
                document = result["documents"][0][i] if result.get("documents") and result["documents"] else ""
                # Post-retrieval agent_id filter
                if agent_id:
                    agent_ids_json = metadata.get("agent_ids_json", "[]")
                    try:
                        agent_ids = json.loads(agent_ids_json)
                    except (json.JSONDecodeError, TypeError):
                        agent_ids = []
                    if agent_id not in agent_ids:
                        continue
                ep = self._metadata_to_episode(doc_id, document, metadata)
                if self._verify_on_recall:
                    stored_hash = metadata.get("content_hash", "")
                    _verify_episode_hash(ep, stored_hash, metadata, self._collection)
                episodes.append(ep)
                if len(episodes) >= limit:
                    break

        # AD-567d: Record deliberate recall access for activation tracking
        if episodes and self._activation_tracker:
            try:
                await self._activation_tracker.record_batch_access(
                    [ep.id for ep in episodes], access_type="recall"
                )
            except Exception:
                logger.debug("AD-567d: Activation tracking failed", exc_info=True)

        # AD-607a/c: anchor-aware recall anomaly gate
        if getattr(self, "_security_config", None) is not None and episodes:
            _aq = _AnchorQueryView(
                watch_section=watch_section,
                channel=channel,
                department=department,
                trigger_agent=trigger_agent or agent_id,
                trigger_type=trigger_type,
            )
            filtered: list[Episode] = []
            for ep in episodes:
                if self._security_anomaly_drop(
                    ep, query=semantic_query, anchor_query=_aq,
                ):
                    continue
                filtered.append(ep)
            episodes = filtered

        return episodes
