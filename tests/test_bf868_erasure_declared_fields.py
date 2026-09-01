"""BF-868 (#1343): erasure reads attachment ids from DECLARED fields only.

``ErasureManager`` used to find attachment ids by scanning every string
anywhere in the episode payload with a bare ``\\b[a-f0-9]{64}\\b`` regex --
inferring identity from SHAPE. Any coincidentally-shaped token became an
attachment id and was unlinked.

``AttachmentStore.unlink`` is a HARD delete with no refcount, so one wrong id
is permanent loss of a file nothing referenced.

The genuine producers, enumerated by walking every ``Episode(`` and
``store_episode(`` call in ``src/``:

  anchors.visual_attachment_ref                     AD-987 group fan-out
  outcomes[].attachment_ids                         AD-720d-3 Captain vision
  outcomes[].attachment_ref                         AD-733 perception anchor
  outcomes[].per_attachment_timing[].attachment_id  AD-720d-1 latency record
  <metadata>.attachment_id                          AD-730-3 image gen

All typed. No production path embeds an attachment id in free text, so the
free-text scan had no genuine producer to serve.

Each producer is exercised through BOTH payload shapes it is reachable in:
``get_by_ids`` yields nested ``outcomes``/``anchors``; the
``get_episode_metadata`` fallback yields a FLAT ChromaDB row carrying
``outcomes_json``/``anchors_json`` as JSON strings. A narrowing that only
handled the nested shape would erase nothing on the fallback path.
"""

from __future__ import annotations

import dataclasses
import json
import logging

import pytest

from probos.knowledge.erasure import ErasureManager

_REAL = "a" * 64
_UNRELATED = "b" * 64


@dataclasses.dataclass
class _Episode:
    id: str
    agent_ids: list[str] = dataclasses.field(default_factory=list)
    user_input: str = ""
    reflection: str = ""
    outcomes: list[dict] = dataclasses.field(default_factory=list)
    anchors: dict | None = None
    failed_tool_names: list[str] = dataclasses.field(default_factory=list)
    self_contradicted_channels: list[str] = dataclasses.field(default_factory=list)


class _FakeEpisodicMemory:
    def __init__(self, episodes: list[_Episode]) -> None:
        self._episodes = episodes

    async def get_by_ids(self, ids: list[str]) -> list[_Episode]:
        return [e for e in self._episodes if e.id in ids]

    async def list_episodes(self, limit: int | None = None) -> list[_Episode]:
        return list(self._episodes)

    async def evict_by_ids(self, ids: list[str], reason: str = "") -> int:
        return len(ids)


class _FakeMetadataOnlyMemory:
    """``get_by_ids`` finds nothing, so erasure takes the FLAT fallback.

    Reproduces the live case where ``_metadata_to_episode`` cannot rehydrate a
    row (episodic.py:2028 swallows the failure and omits the id) while
    ``get_episode_metadata`` still returns the raw ChromaDB metadata.
    """

    def __init__(self, metadata: dict) -> None:
        self._metadata = metadata

    async def get_by_ids(self, ids: list[str]) -> list[_Episode]:
        return []

    async def get_episode_metadata(self, episode_id: str) -> dict:
        return self._metadata

    async def evict_by_ids(self, ids: list[str], reason: str = "") -> int:
        return len(ids)


class _FakeAttachmentStore:
    def __init__(self) -> None:
        self.deleted: set[str] = set()

    async def unlink(self, content_hash: str) -> bool:
        self.deleted.add(content_hash)
        return True


class _FakeAuditLog:
    def __init__(self) -> None:
        self.markers: list[str] = []

    async def mark_deleted(self, resource_marker: str) -> int:
        self.markers.append(resource_marker)
        return 1


async def _erase(episode: _Episode) -> _FakeAttachmentStore:
    store = _FakeAttachmentStore()
    manager = ErasureManager(
        episodic_memory=_FakeEpisodicMemory([episode]),
        attachment_store=store,
        audit_log=_FakeAuditLog(),
    )
    await manager.forget_episode(episode.id)
    return store


async def _erase_from_metadata(metadata: dict) -> _FakeAttachmentStore:
    """Erase through the FLAT ``get_episode_metadata`` fallback shape."""
    store = _FakeAttachmentStore()
    manager = ErasureManager(
        episodic_memory=_FakeMetadataOnlyMemory(metadata),
        attachment_store=store,
        audit_log=_FakeAuditLog(),
    )
    await manager.forget_episode("ep")
    return store


# ── the declared producers still erase ────────────────────────────────────


@pytest.mark.asyncio
async def test_outcomes_attachment_ids_are_erased() -> None:
    """AD-720d-3 Captain-chat vision. Under-erasing here would leave data the
    Captain asked to be forgotten, which is the worse failure."""
    store = await _erase(_Episode(id="ep", outcomes=[{"attachment_ids": [_REAL]}]))
    assert _REAL in store.deleted


@pytest.mark.asyncio
async def test_anchor_visual_attachment_ref_is_erased() -> None:
    """AD-987 group fan-out. A bare string, not a list."""
    store = await _erase(_Episode(id="ep", anchors={"visual_attachment_ref": _REAL}))
    assert _REAL in store.deleted


@pytest.mark.asyncio
async def test_both_producers_in_one_episode_are_both_erased() -> None:
    store = await _erase(_Episode(
        id="ep",
        outcomes=[{"attachment_ids": [_REAL]}],
        anchors={"visual_attachment_ref": _UNRELATED},
    ))
    assert store.deleted == {_REAL, _UNRELATED}


@pytest.mark.asyncio
async def test_several_ids_in_one_outcome_are_all_erased() -> None:
    other = "c" * 64
    store = await _erase(_Episode(id="ep", outcomes=[{"attachment_ids": [_REAL, other]}]))
    assert store.deleted == {_REAL, other}


# ── free text no longer causes a delete ───────────────────────────────────


@pytest.mark.asyncio
async def test_a_hex_string_the_captain_typed_is_not_erased() -> None:
    """The reported defect. ``user_input`` is free text."""
    store = await _erase(_Episode(id="ep", user_input=f"correlate this with {_UNRELATED}"))
    assert store.deleted == set()


@pytest.mark.asyncio
async def test_a_hex_string_an_llm_echoed_into_a_response_is_not_erased() -> None:
    """``outcomes[].response`` sits in the SAME dict as ``attachment_ids``, so
    a key-blind scan of that dict would still delete it."""
    store = await _erase(_Episode(
        id="ep", outcomes=[{"response": f"the digest was {_UNRELATED}"}],
    ))
    assert store.deleted == set()


@pytest.mark.asyncio
async def test_a_hex_shaped_tool_name_is_not_erased() -> None:
    """BF-795 added ``failed_tool_names``; MCP tool names come from the remote
    server, so a hash-suffixed name is not exotic. This is what made the
    pre-existing exposure worth filing."""
    store = await _erase(_Episode(id="ep", failed_tool_names=[_UNRELATED]))
    assert store.deleted == set()


@pytest.mark.asyncio
async def test_a_hex_shaped_channel_label_is_not_erased() -> None:
    """AD-1293's ``self_contradicted_channels``, the original carrier."""
    store = await _erase(_Episode(id="ep", self_contradicted_channels=[_UNRELATED]))
    assert store.deleted == set()


@pytest.mark.asyncio
async def test_a_hex_string_in_reflection_is_not_erased() -> None:
    """AD-987 group episodes put the agent's own reply text into ``reflection``
    -- unbounded agent prose, right beside the anchor that DOES carry a real
    ref."""
    store = await _erase(_Episode(id="ep", reflection=f"agent said: {_UNRELATED}"))
    assert store.deleted == set()


# ── malformed values in a declared field must not reach unlink ────────────


@pytest.mark.asyncio
async def test_a_declared_field_holding_prose_does_not_delete_by_substring() -> None:
    """``fullmatch``, not ``search``: a declared field holds an id, so a value
    that merely CONTAINS one is malformed, not salvageable."""
    store = await _erase(_Episode(
        id="ep", anchors={"visual_attachment_ref": f"see {_UNRELATED} for detail"},
    ))
    assert store.deleted == set()


@pytest.mark.asyncio
async def test_non_string_entries_in_a_declared_list_are_skipped() -> None:
    store = await _erase(_Episode(
        id="ep", outcomes=[{"attachment_ids": [None, 42, {"nested": _UNRELATED}, _REAL]}],
    ))
    assert store.deleted == {_REAL}


@pytest.mark.asyncio
async def test_a_short_or_uppercase_value_is_not_treated_as_an_id() -> None:
    store = await _erase(_Episode(id="ep", outcomes=[{"attachment_ids": ["a" * 63, "zz"]}]))
    assert store.deleted == set()


@pytest.mark.asyncio
async def test_surrounding_whitespace_is_tolerated() -> None:
    """A declared field whose value merely picked up whitespace is still a
    genuine reference -- refusing it would UNDER-erase, the worse failure."""
    store = await _erase(_Episode(id="ep", anchors={"visual_attachment_ref": f"  {_REAL}\n"}))
    assert store.deleted == {_REAL}


@pytest.mark.asyncio
async def test_an_absent_or_malformed_anchors_block_is_harmless() -> None:
    for anchors in (None, {}, "not-a-dict", []):
        store = await _erase(_Episode(id="ep", anchors=anchors))  # type: ignore[arg-type]
        assert store.deleted == set()


@pytest.mark.asyncio
async def test_a_malformed_outcomes_list_is_harmless() -> None:
    store = await _erase(_Episode(id="ep", outcomes=["not-a-dict", None, 7]))  # type: ignore[list-item]
    assert store.deleted == set()


# ── production-shaped fixtures, one per producer ──────────────────────────
#
# Copied from the live construction sites rather than minimised, so a producer
# that later drops or renames its key is not silently still "covered" here by a
# hand-written stand-in that no longer resembles what it writes.


def _p1_group_fanout(ref: str) -> _Episode:
    """AD-987 group fan-out — ``routers/thread_fanout.py:827``."""
    return _Episode(
        id="ep", agent_ids=["scout"],
        user_input="[group] Captain: what is on screen?",
        reflection="SCOUT said in group chat: a bar chart.",
        outcomes=[{
            "intent": "direct_message", "success": True,
            "response": "a bar chart.", "session_type": "group",
            "callsign": "SCOUT", "source": "group_chat_fanout",
        }],
        anchors={
            "channel": "chat", "trigger_type": "group_fanout",
            "participants": ["captain", "SCOUT"], "trigger_agent": "captain",
            "chat_thread_id": "thr-1",
            "visual_attachment_ref": ref, "visual_description": "a bar chart",
        },
    )


def _p2_captain_vision(ref: str) -> _Episode:
    """AD-720d-3 Captain-chat vision — ``routers/chat.py:734``."""
    return _Episode(
        id="ep", agent_ids=["captain"], user_input="what is this?",
        outcomes=[{
            "intent": "captain_chat_vision", "success": True,
            "response": "a schematic.", "has_image_attachment": True,
            "image_count": 1, "failed_image_count": 0,
            "per_attachment_timing": [
                {"attachment_id": ref, "mime": "image/png",
                 "resolve_ms": 4.2, "ok": True},
            ],
            "attachment_ids": [ref],
            "llm_tier": "vision", "llm_model": "qwen3.6",
        }],
        anchors={"channel": "captain_chat", "trigger_type": "vision_attachment"},
    )


def _p3_perception_anchor(ref: str) -> _Episode:
    """AD-733 perception anchor — ``routers/perception.py:96`` and the same
    outcome shape from ``perception/consumer.py:1079``."""
    return _Episode(
        id="ep", user_input="",
        reflection="Camera stream began (session=abcdefgh, sha=aaaaaaaa).",
        outcomes=[{
            "intent": "vision_observation", "success": True,
            "session_id": "sess-1", "attachment_ref": ref, "source": "camera",
        }],
        anchors={
            "channel": "perception", "trigger_type": "camera_stream_began",
            "trigger_agent": "captain",
        },
    )


def _p4_image_gen_metadata(ref: str) -> dict:
    """AD-730-3 image gen — ``cognitive/image_gen_dispatch.py:100``.

    The only producer that writes into episode METADATA rather than an
    ``Episode`` field, so the flat row is the only shape it is reachable in.
    """
    return {
        "anchored": True, "ad": "AD-730-3",
        "attachment_id": ref, "mime": "image/png",
    }


def _p5_dm_per_attachment(ref: str) -> _Episode:
    """AD-720d-1 latency record — ``cognitive/dm/reply_pipeline.py:1926``.

    This episode has NO ``attachment_ids`` key. ``per_attachment_timing`` is
    the ONLY place the id appears, so a 1:1 DM about an image erased nothing
    while the allowlist covered only the plural key.
    """
    return _Episode(
        id="ep", agent_ids=["scout"],
        user_input="[1:1 with SCOUT] Captain: describe this",
        reflection="Captain had a 1:1 conversation with SCOUT via HXI.",
        outcomes=[{
            "intent": "direct_message", "success": True,
            "response": "a wiring diagram.", "session_type": "1:1",
            "callsign": "SCOUT", "source": "hxi_profile",
            "agent_type": "cognitive", "has_image_attachment": True,
            "image_count": 1, "failed_image_count": 0,
            "per_attachment_timing": [
                {"attachment_id": ref, "mime": "image/png",
                 "resolve_ms": 7.9, "ok": True},
            ],
        }],
        anchors={"channel": "dm", "trigger_type": "direct_message"},
    )


def _as_flat_row(episode: _Episode) -> dict:
    """The flat ChromaDB row ``episodic.py:3550-3557`` encodes this episode as.

    ``outcomes``/``anchors`` become JSON STRINGS; ``anchors_json`` is ``""``
    when the episode has no anchors.
    """
    return {
        "outcomes_json": json.dumps(episode.outcomes),
        "anchors_json": json.dumps(episode.anchors) if episode.anchors else "",
        "user_input": episode.user_input,
        "reflection": episode.reflection,
        "source": "direct",
    }


# ── every producer erases, through the NESTED shape ───────────────────────


@pytest.mark.asyncio
async def test_p3_perception_attachment_ref_is_erased() -> None:
    """Singular ``outcomes[].attachment_ref``. Every ambient camera/screen
    frame anchors through this key, so missing it left the largest volume of
    supposedly-forgotten imagery on disk."""
    store = await _erase(_p3_perception_anchor(_REAL))
    assert _REAL in store.deleted


@pytest.mark.asyncio
async def test_p5_dm_per_attachment_timing_is_erased() -> None:
    """The nested record list. On the 1:1 DM path there is no other carrier."""
    store = await _erase(_p5_dm_per_attachment(_REAL))
    assert _REAL in store.deleted


@pytest.mark.asyncio
async def test_p2_captain_vision_erases_both_of_its_carriers() -> None:
    """``chat.py`` writes the id twice -- once in ``attachment_ids`` and again
    inside ``per_attachment_timing``. Both resolve to the same id, so the
    result is one delete, not a double unlink."""
    store = await _erase(_p2_captain_vision(_REAL))
    assert store.deleted == {_REAL}


# ── every producer erases, through the FLAT metadata fallback ─────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make_episode",
    [_p1_group_fanout, _p2_captain_vision, _p3_perception_anchor, _p5_dm_per_attachment],
    ids=["p1_group_fanout", "p2_captain_vision", "p3_perception", "p5_dm_timing"],
)
async def test_each_producer_erases_through_the_flat_metadata_fallback(
    make_episode,
) -> None:
    """``get_episode_metadata`` returns the raw ChromaDB row, where outcomes and
    anchors are JSON STRINGS. Before BF-868 normalised that shape the fallback
    extracted nothing, so any episode reached this way erased zero attachments
    -- a silent under-erase in the manager whose whole job is erasing."""
    store = await _erase_from_metadata(_as_flat_row(make_episode(_REAL)))
    assert _REAL in store.deleted


@pytest.mark.asyncio
async def test_p4_image_gen_metadata_attachment_id_is_erased() -> None:
    """AD-730-3 writes a top-level metadata key, so it is reachable only here.

    NOTE: ``image_gen_dispatch._maybe_write_anchored_episode`` is currently
    gated off in production -- it requires ``store_episode`` on the episodic
    memory and ``EpisodicMemory`` does not define one -- so no episode carries
    this key today. Covered anyway: the extractor is the component under test,
    and leaving the key out would hand the next person a silent under-erase the
    moment that guard is repaired.
    """
    store = await _erase_from_metadata(_p4_image_gen_metadata(_REAL))
    assert _REAL in store.deleted


@pytest.mark.asyncio
async def test_flat_fallback_still_refuses_free_text() -> None:
    """The fallback must not become a second, laxer extractor: the flat row
    carries ``user_input`` and ``reflection`` as plain top-level strings."""
    store = await _erase_from_metadata({
        "user_input": f"correlate this with {_UNRELATED}",
        "reflection": f"agent said: {_UNRELATED}",
        "outcomes_json": json.dumps([{"response": f"digest {_UNRELATED}"}]),
        "anchors_json": "",
    })
    assert store.deleted == set()


@pytest.mark.asyncio
async def test_unparseable_outcomes_json_degrades_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Malformed JSON must not raise -- but it must not be silent either.

    Erasing nothing is the exact failure this decode exists to fix, so a
    swallow with no record would reproduce it one layer down.
    """
    with caplog.at_level(logging.WARNING, logger="probos.knowledge.erasure"):
        store = await _erase_from_metadata({
            "outcomes_json": "{not json",
            "anchors_json": json.dumps({"visual_attachment_ref": _REAL}),
        })

    # The half that DID decode still erases; only the broken half is lost.
    assert store.deleted == {_REAL}
    assert any(
        "outcomes_json" in record.getMessage() for record in caplog.records
    ), "a decode failure must be logged, not swallowed"


@pytest.mark.asyncio
async def test_an_empty_anchors_json_is_not_reported_as_a_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``anchors_json`` is ``""`` for every anchorless episode (episodic.py:3557).
    Warning on those would bury the real decode failures in noise."""
    with caplog.at_level(logging.WARNING, logger="probos.knowledge.erasure"):
        await _erase_from_metadata({
            "outcomes_json": json.dumps([{"attachment_ref": _REAL}]),
            "anchors_json": "",
        })
    assert caplog.records == []


# ── the cascades inherit the same extraction ──────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make_episode",
    [_p1_group_fanout, _p2_captain_vision, _p3_perception_anchor, _p5_dm_per_attachment],
    ids=["p1_group_fanout", "p2_captain_vision", "p3_perception", "p5_dm_timing"],
)
async def test_forget_resource_cascade_erases_every_producer(make_episode) -> None:
    """``forget_resource`` fans out to ``forget_episode``, so a gap in the
    extractor is inherited by the whole cascade -- the Captain asks to forget a
    resource and the attachments quietly stay."""
    episode = make_episode(_REAL)
    episode.user_input = f"{episode.user_input} /var/log/secret.png"
    store = _FakeAttachmentStore()
    manager = ErasureManager(
        episodic_memory=_FakeEpisodicMemory([episode]),
        attachment_store=store,
        audit_log=_FakeAuditLog(),
    )
    result = await manager.forget_resource("/var/log/secret.png")
    assert _REAL in store.deleted
    assert result.deleted_attachment_ids == [_REAL]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make_episode",
    [_p1_group_fanout, _p2_captain_vision, _p5_dm_per_attachment],
    ids=["p1_group_fanout", "p2_captain_vision", "p5_dm_timing"],
)
async def test_forget_agent_memory_cascade_erases_every_producer(make_episode) -> None:
    """Same inheritance through the agent cascade. ``_p3_perception_anchor`` is
    excluded: its production shape carries no ``agent_ids`` (the AD-733 anchor
    is written without an observer), so it is not selectable by this cascade."""
    episode = make_episode(_REAL)
    store = _FakeAttachmentStore()
    manager = ErasureManager(
        episodic_memory=_FakeEpisodicMemory([episode]),
        attachment_store=store,
        audit_log=_FakeAuditLog(),
    )
    result = await manager.forget_agent_memory(episode.agent_ids[0])
    assert _REAL in store.deleted
    assert result.deleted_attachment_ids == [_REAL]


@pytest.mark.asyncio
async def test_cascades_still_refuse_a_hex_shaped_tool_name() -> None:
    """The anti-over-erase guarantee must hold through the cascade too, not
    only through the single-episode entry point."""
    episode = _Episode(
        id="ep", agent_ids=["scout"],
        user_input="/var/log/secret.png",
        failed_tool_names=[_UNRELATED],
    )
    store = _FakeAttachmentStore()
    manager = ErasureManager(
        episodic_memory=_FakeEpisodicMemory([episode]),
        attachment_store=store,
        audit_log=_FakeAuditLog(),
    )
    await manager.forget_resource("/var/log/secret.png")
    await manager.forget_agent_memory("scout")
    assert store.deleted == set()
