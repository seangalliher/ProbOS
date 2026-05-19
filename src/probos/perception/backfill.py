"""BF-312 — One-shot backfill for orphaned perception-anchored episodes.

Wave 171 (AD-733a) shipped the vision consumer that writes anchored episodes
on every flagged frame. BF-311 (May 18) fixed the going-forward bug where
those episodes were stored with ``agent_ids = []``, making them invisible to
per-agent episodic recall.

This backfill stamps the pre-BF-311 orphaned perception episodes with the
currently-registered observer agent_ids so the agents that should have seen
those observations can recall them. Idempotent — re-running finds nothing
to update and exits fast.

Approach:
- Mirror the established ``migrate_episode_agent_ids`` pattern (cognitive
  /episodic.py:85): single chroma ``get`` → filter to perception-anchored
  episodes with empty ``agent_ids_json`` → batched ``upsert`` → record
  the participant index for the updated episodes.
- ``observer_agent_ids`` is supplied by the caller (typically
  ``startup/finalize.py`` after the vision consumer is wired). We don't
  guess at historical observers — we apply the present roster, which is
  the cleanest defensible answer when no historical record exists.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


async def backfill_perception_episode_agent_ids(
    episodic_memory: Any,
    observer_agent_ids: list[str],
) -> int:
    """Stamp orphaned perception-anchored episodes with the observer agent ids.

    Returns the count of episodes updated. Returns 0 if no orphans found
    (idempotent) or if ``observer_agent_ids`` is empty (nothing to stamp).
    """
    if not observer_agent_ids:
        logger.debug(
            "BF-312: backfill skipped (no observer agent_ids supplied)"
        )
        return 0

    collection = getattr(episodic_memory, "_collection", None)
    if collection is None:
        logger.debug("BF-312: backfill skipped (no chroma collection on episodic_memory)")
        return 0

    t0 = time.time()
    updated = 0

    try:
        # Single round-trip: pull all metadatas + documents, filter in Python.
        # The where-clause filter on chroma is restrictive enough we'd still
        # have to iterate anyway (anchor_channel + agent_ids_json composite),
        # and the existing migrate_episode_agent_ids does it this way.
        result = collection.get(include=["metadatas", "documents"])
        if not result or not result.get("ids"):
            return 0

        ids_list = result["ids"]
        metadatas = result.get("metadatas", [])
        documents = result.get("documents", [])

        new_ids_json = json.dumps(list(observer_agent_ids))

        batch_ids: list[str] = []
        batch_metas: list[dict[str, Any]] = []
        batch_docs: list[str] = []
        # Tuples for participant index update.
        participant_batch: list[tuple[str, list[str], list[str]]] = []

        for i, ep_id in enumerate(ids_list):
            meta = metadatas[i] if i < len(metadatas) else {}
            if meta.get("anchor_channel") != "perception":
                continue
            current = meta.get("agent_ids_json", "[]")
            try:
                current_list = json.loads(current)
            except (json.JSONDecodeError, TypeError):
                current_list = []
            if current_list:
                # Already tagged (either correctly by BF-311 or partially by
                # an earlier observer registration). Don't clobber.
                continue

            meta["agent_ids_json"] = new_ids_json
            batch_ids.append(ep_id)
            batch_metas.append(meta)
            batch_docs.append(documents[i] if i < len(documents) else "")
            # Participants list comes from the anchor frame, not the agents.
            # The episode anchor's ``participants`` is empty for perception
            # observations in v1, so we leave that side of the index alone.
            participant_batch.append((ep_id, list(observer_agent_ids), []))

        if not batch_ids:
            logger.debug(
                "BF-312: no orphaned perception episodes found (%.2fs)",
                time.time() - t0,
            )
            return 0

        # Single batched upsert (mirrors BF-134 pattern).
        collection.upsert(
            ids=batch_ids,
            metadatas=batch_metas,
            documents=batch_docs,
        )

        # Update the participant index sidecar if present so per-agent
        # recall actually surfaces these episodes via the index path.
        participant_index = getattr(episodic_memory, "_participant_index", None)
        if participant_index is not None:
            try:
                await participant_index.record_episode_batch(participant_batch)
            except Exception:
                logger.warning(
                    "BF-312: participant index update failed for %d episodes; "
                    "chroma metadata is updated but the sidecar may be stale "
                    "until the next index rebuild.",
                    len(batch_ids), exc_info=True,
                )

        updated = len(batch_ids)
        logger.info(
            "BF-312: backfilled %d orphaned perception episode(s) with "
            "agent_ids=%s (%.2fs)",
            updated, observer_agent_ids, time.time() - t0,
        )
        return updated

    except Exception:
        logger.warning(
            "BF-312: perception agent_ids backfill failed; orphaned episodes "
            "remain unrecallable by per-agent queries until next attempt.",
            exc_info=True,
        )
        return 0


__all__ = ["backfill_perception_episode_agent_ids"]
