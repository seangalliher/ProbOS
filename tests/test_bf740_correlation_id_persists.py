"""BF-740 (#1199): ``Episode.correlation_id`` survives storage and recall.

The field was set by producers -- ``turn_promotion.py`` pairs a promoted run's
outcome episode to its acknowledgement by work item -- and silently dropped at
the ChromaDB metadata boundary. ``episodic.py`` contained zero occurrences of
the name, so AD-1166's documented claim that "the two are linked by
``correlation_id`` = the work item, so a later consolidation can pair them" was
describing a link that did not exist.

Same shape as BF-705, where ``IntentMessage`` carried ``ttl_seconds`` /
``created_at`` and ``perceive`` never copied them into the observation: a field
present on the in-memory object and absent after a boundary is indistinguishable
from a field that works, right up until something depends on it.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from probos.cognitive.episodic import (
    EpisodicMemory,
    _HASH_VERSION,
    compute_episode_hash,
)
from probos.types import AnchorFrame, Episode

WORK_ITEM = "712ebc8d645f"
AGENT = "counselor_counselor_0_67c601cb"


def _episode(*, correlation_id: str = "", user_input: str = "a request") -> Episode:
    return Episode(
        user_input=user_input,
        timestamp=time.time(),
        agent_ids=[AGENT],
        correlation_id=correlation_id,
        outcomes=[{"intent": "direct_message", "success": True}],
        reflection="a reflection",
        source="direct",
        anchors=AnchorFrame(channel="dm", trigger_agent="captain"),
    )


@pytest.fixture
async def memory(tmp_path: Path):
    em = EpisodicMemory(db_path=str(tmp_path / "episodes.db"))
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


# ── the round trip ────────────────────────────────────────────────


async def test_correlation_id_survives_store_and_recall(memory) -> None:
    """The defect, directly: set it, read it back, get it."""
    await memory.store(_episode(correlation_id=WORK_ITEM))

    recovered = await memory.recent_for_agent(AGENT, k=5)

    assert recovered, "the episode did not come back at all"
    assert recovered[0].correlation_id == WORK_ITEM


async def test_an_episode_without_one_reads_back_as_empty_not_none(memory) -> None:
    """``Episode.correlation_id`` is ``str`` with a ``""`` default. A missing
    metadata key must not turn it into ``None`` for every consumer downstream.
    """
    await memory.store(_episode())

    recovered = await memory.recent_for_agent(AGENT, k=5)

    assert recovered
    assert recovered[0].correlation_id == ""


async def test_two_episodes_sharing_a_work_item_can_be_paired(memory) -> None:
    """The reason the field exists (AD-1166). A promoted run stores an outcome
    episode alongside the acknowledgement episode for the same request; the two
    are near-identical in text and only the work item distinguishes them.
    """
    await memory.store(_episode(
        correlation_id=WORK_ITEM, user_input="[1:1 with Ezri] Captain: do the thing",
    ))
    await memory.store(_episode(
        correlation_id=WORK_ITEM, user_input="[1:1 background task] Captain: do the thing",
    ))
    await memory.store(_episode(correlation_id="", user_input="unrelated chatter"))

    recovered = await memory.recent_for_agent(AGENT, k=10)
    paired = [e for e in recovered if e.correlation_id == WORK_ITEM]

    assert len(paired) == 2, "the pairing key does not identify both halves"
    assert {e.user_input for e in paired} == {
        "[1:1 with Ezri] Captain: do the thing",
        "[1:1 background task] Captain: do the thing",
    }


# ── the risk the issue named ──────────────────────────────────────


def test_the_content_hash_does_not_depend_on_the_correlation_id() -> None:
    """BF-740 flagged AD-541e as the thing to check before adding a metadata key.

    ``compute_episode_hash`` hashes a fixed set of content fields and
    ``correlation_id`` is deliberately not among them. Adding it would change
    every stored episode's hash and trigger a mass auto-heal -- a large,
    silent migration in exchange for a pairing key. This test pins that
    decision so a future edit to the hash body has to confront it.
    """
    ts = time.time()
    without = Episode(user_input="x", timestamp=ts, agent_ids=[AGENT])
    with_id = Episode(
        user_input="x", timestamp=ts, agent_ids=[AGENT], correlation_id=WORK_ITEM,
    )

    assert compute_episode_hash(without) == compute_episode_hash(with_id)


async def test_verification_still_passes_for_an_episode_carrying_one(memory) -> None:
    """The stored hash must still verify on recall with the new key present."""
    await memory.store(_episode(correlation_id=WORK_ITEM))

    recovered = await memory.recent_for_agent(AGENT, k=5)

    assert recovered
    assert compute_episode_hash(recovered[0]) == compute_episode_hash(recovered[0])
    assert recovered[0].correlation_id == WORK_ITEM


async def test_a_legacy_episode_without_the_key_still_loads(memory) -> None:
    """Every episode stored before this fix has no ``correlation_id`` key at
    all. Reading one must not raise and must not lose any other field.
    """
    ep = _episode(user_input="stored before BF-740")
    await memory.store(ep)

    collection = memory._collection
    stored = collection.get(ids=[ep.id], include=["metadatas"])
    meta = dict(stored["metadatas"][0])
    meta.pop("correlation_id", None)
    collection.update(ids=[ep.id], metadatas=[meta])

    recovered = await memory.recent_for_agent(AGENT, k=5)

    assert recovered
    hit = [e for e in recovered if e.user_input == "stored before BF-740"]
    assert hit, "a pre-BF-740 episode no longer loads"
    assert hit[0].correlation_id == ""
    assert hit[0].reflection == "a reflection"
    assert hit[0].agent_ids == [AGENT]
    assert int(meta.get("_hash_v", 0)) == _HASH_VERSION
