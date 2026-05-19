"""BF-312 — backfill orphaned perception-anchored episodes with agent_ids."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.perception.backfill import backfill_perception_episode_agent_ids


def _make_episodic(eps: list[dict[str, Any]]) -> Any:
    """Build a stand-in episodic_memory with a chroma-shaped _collection."""
    collection = MagicMock()
    collection.get.return_value = {
        "ids": [e["id"] for e in eps],
        "metadatas": [e["meta"] for e in eps],
        "documents": [e.get("doc", "") for e in eps],
    }
    collection.upsert = MagicMock()
    em = MagicMock()
    em._collection = collection
    em._participant_index = None
    return em, collection


@pytest.mark.asyncio
async def test_stamps_orphaned_perception_episodes_with_observer_ids() -> None:
    em, col = _make_episodic([
        {
            "id": "ep-white-1",
            "meta": {
                "anchor_channel": "perception",
                "agent_ids_json": "[]",
                "reflection": "...white t-shirt...",
            },
        },
        {
            "id": "ep-white-2",
            "meta": {
                "anchor_channel": "perception",
                "agent_ids_json": "[]",
                "reflection": "...white t-shirt later...",
            },
        },
    ])

    n = await backfill_perception_episode_agent_ids(em, ["ezri", "data"])

    assert n == 2
    col.upsert.assert_called_once()
    kwargs = col.upsert.call_args.kwargs
    assert set(kwargs["ids"]) == {"ep-white-1", "ep-white-2"}
    for meta in kwargs["metadatas"]:
        assert json.loads(meta["agent_ids_json"]) == ["ezri", "data"]


@pytest.mark.asyncio
async def test_idempotent_when_no_orphans() -> None:
    em, col = _make_episodic([
        {
            "id": "ep-tagged",
            "meta": {
                "anchor_channel": "perception",
                "agent_ids_json": json.dumps(["ezri"]),
                "reflection": "...already tagged...",
            },
        },
    ])

    n = await backfill_perception_episode_agent_ids(em, ["ezri"])

    assert n == 0
    col.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_does_not_touch_non_perception_episodes() -> None:
    em, col = _make_episodic([
        {
            "id": "ep-dm",
            "meta": {
                "anchor_channel": "direct_message",
                "agent_ids_json": "[]",
                "reflection": "...a DM that lost its agent_ids...",
            },
        },
    ])

    n = await backfill_perception_episode_agent_ids(em, ["ezri"])

    assert n == 0
    col.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_does_not_clobber_partially_tagged_perception_episodes() -> None:
    """If an episode already has SOME agent_id (the BF-311 partial case where
    a single UUID was tagged), don't overwrite it."""
    em, col = _make_episodic([
        {
            "id": "ep-partial",
            "meta": {
                "anchor_channel": "perception",
                "agent_ids_json": json.dumps(["c53aef31-57e7-497d-ad71-0f7b639b0c4e"]),
            },
        },
        {
            "id": "ep-empty",
            "meta": {
                "anchor_channel": "perception",
                "agent_ids_json": "[]",
            },
        },
    ])

    n = await backfill_perception_episode_agent_ids(em, ["ezri"])

    assert n == 1
    kwargs = col.upsert.call_args.kwargs
    assert kwargs["ids"] == ["ep-empty"]


@pytest.mark.asyncio
async def test_skips_when_observer_list_empty() -> None:
    em, col = _make_episodic([
        {
            "id": "ep-orphan",
            "meta": {"anchor_channel": "perception", "agent_ids_json": "[]"},
        },
    ])
    n = await backfill_perception_episode_agent_ids(em, [])
    assert n == 0
    col.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_updates_participant_index_when_present() -> None:
    em, col = _make_episodic([
        {
            "id": "ep-orphan",
            "meta": {"anchor_channel": "perception", "agent_ids_json": "[]"},
        },
    ])
    em._participant_index = MagicMock()
    em._participant_index.record_episode_batch = AsyncMock()

    n = await backfill_perception_episode_agent_ids(em, ["ezri"])

    assert n == 1
    em._participant_index.record_episode_batch.assert_awaited_once()
    batch_arg = em._participant_index.record_episode_batch.call_args.args[0]
    assert batch_arg == [("ep-orphan", ["ezri"], [])]
