"""BF-869 (#1345): a fused frame's second attachment ref must survive into the
episode, and erasure must reach it.

`VisionAggregator._fuse` binds one attachment ref per source and hands the
consumer PARALLEL lists -- ``attachment_refs`` and ``sources`` -- each with a
singular first-element alias. The consumer preserved ``sources`` but reduced the
refs to ``attachment_refs[0]`` and wrote only the singular ``attachment_ref``,
so on a two-source frame the second ref was recorded NOWHERE.

That is worse than an ordinary under-erase. ``ErasureManager`` derives what to
unlink from what the episode declares, so a ref the episode never recorded
survives an explicit "forget this" AND is orphaned -- no episode points at it,
so no episode-driven cleanup will ever find it either.

Reproduced against the live path before the fix (issue comment): the screen
frame's sha appeared nowhere in the stored episode while ``sources`` kept both.

The middle test here is the one that matters. Each half of this chain can be
correct while the chain is dead, which is this repository's most common defect
shape, so one test spans producer -> episode -> ErasureManager.
"""
from __future__ import annotations

import dataclasses
import hashlib
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from probos.knowledge.erasure import ErasureManager
from probos.types import Episode, IntentMessage, LLMResponse

_CAM = "a" * 64
_SCR = "b" * 64


class _FakeEpisodicMemory:
    def __init__(self, episodes: list) -> None:
        self._episodes = episodes

    async def get_by_ids(self, ids: list[str]) -> list:
        return [e for e in self._episodes if e.id in ids]

    async def list_episodes(self, limit: int | None = None) -> list:
        return list(self._episodes)

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


async def _erase(episode) -> _FakeAttachmentStore:
    """Drive the REAL ErasureManager over one episode."""
    store = _FakeAttachmentStore()
    manager = ErasureManager(
        episodic_memory=_FakeEpisodicMemory([episode]),
        attachment_store=store,
        audit_log=_FakeAuditLog(),
    )
    await manager.forget_episode(episode.id)
    return store


def _jpeg(color: tuple[int, int, int]) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (16, 16), color=color).save(buf, "JPEG", quality=80)
    return buf.getvalue()


def _all_strings(obj) -> set[str]:
    """Every string anywhere in a nested structure.

    Structured traversal rather than a substring scan of ``repr``: the claim
    being made is "this ref is recorded NOWHERE in the episode", which has to
    look in every field, but a repr scan would silently change meaning if the
    dataclass repr ever did.
    """
    if isinstance(obj, str):
        return {obj}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        obj = dataclasses.asdict(obj)
    if isinstance(obj, dict):
        found: set[str] = set()
        for key, value in obj.items():
            found |= _all_strings(key) | _all_strings(value)
        return found
    if isinstance(obj, (list, tuple, set, frozenset)):
        found = set()
        for item in obj:
            found |= _all_strings(item)
        return found
    return set()


async def _run_fused_frame(
    tmp_path: Path, *, fused: bool
) -> tuple[Episode, str, str]:
    """Drive the real ``VisionConsumer._process``.

    Returns the stored Episode and the two shas. ``Episode`` is frozen, so the
    shas travel alongside it rather than on it.

    ``fused=False`` sends the single-source shape, so the same helper covers the
    regression and the unchanged legacy path.
    """
    from probos.attachments.filesystem_store import FilesystemAttachmentStore
    from probos.config import SystemConfig
    from probos.perception.consumer import (
        VisionConsumer,
        reset_working_memories_for_tests,
    )
    from probos.routers.chat import _ATTACHMENT_STORE_CACHE

    attachments = tmp_path / "attachments"
    attachments.mkdir(parents=True, exist_ok=True)

    runtime = MagicMock()
    cfg = SystemConfig()
    cfg.perception.enabled = True
    cfg.attachments.attachments_dir = str(attachments)
    runtime.config = cfg
    store = FilesystemAttachmentStore(attachments)
    runtime._attachment_store = store
    runtime.intent_bus = MagicMock()
    runtime.episodic_memory = MagicMock()
    runtime.episodic_memory.store = AsyncMock(return_value=None)
    runtime.llm_client = MagicMock()
    runtime.llm_client.complete = AsyncMock(
        return_value=LLMResponse(content="a desk and a screen", model="vision-fake")
    )
    runtime.profile_store = MagicMock()
    runtime.profile_store.get.return_value = None

    _ATTACHMENT_STORE_CACHE.clear()
    reset_working_memories_for_tests()
    try:
        cam, scr = _jpeg((20, 20, 20)), _jpeg((200, 30, 30))
        cam_sha = hashlib.sha256(cam).hexdigest()
        scr_sha = hashlib.sha256(scr).hexdigest()
        await store.write(cam_sha, cam, "image/jpeg")
        await store.write(scr_sha, scr, "image/jpeg")
        assert cam_sha != scr_sha, "premise: the two frames collided"

        if fused:
            params = {
                "attachment_refs": [cam_sha, scr_sha],
                "attachment_ref": cam_sha,
                "sources": ["camera", "screen"],
                "source": "camera",
                "fused": True,
                "session_id": "bf869",
            }
        else:
            params = {
                "attachment_ref": cam_sha,
                "source": "camera",
                "session_id": "bf869-single",
            }

        consumer = VisionConsumer(runtime)
        consumer.register_observer("counselor")
        await consumer._process(
            IntentMessage(intent="vision_observation", params=params)
        )

        stored = runtime.episodic_memory.store.await_count
        assert stored == 1, (
            f"premise: {stored} episodes stored, expected 1 -- the probe never "
            "reached the anchor, so any conclusion below is meaningless"
        )
        episode = runtime.episodic_memory.store.await_args.args[0]
        return episode, cam_sha, scr_sha
    finally:
        reset_working_memories_for_tests()


# ── producer ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_fused_frame_records_every_bound_ref(tmp_path: Path) -> None:
    """Both refs reach the episode, not just ``attachment_refs[0]``."""
    episode, cam_sha, scr_sha = await _run_fused_frame(tmp_path, fused=True)
    outcome = episode.outcomes[0]

    assert outcome["attachment_refs"] == [cam_sha, scr_sha]
    # The whole-episode check is the one that matters: before the fix the
    # screen sha was absent from EVERY field, not merely from this key.
    recorded = _all_strings(episode)
    assert cam_sha in recorded, "premise: the primary ref is not recorded either"
    assert scr_sha in recorded, "the second ref is recorded nowhere"


@pytest.mark.asyncio
async def test_the_singular_alias_is_unchanged(tmp_path: Path) -> None:
    """Existing readers of ``attachment_ref`` see exactly what they did.

    The sibling key is additive. ``sources``/``source`` already carried this
    shape, and the singular alias keeps pointing at the primary frame.
    """
    episode, cam_sha, _ = await _run_fused_frame(tmp_path, fused=True)
    outcome = episode.outcomes[0]

    assert outcome["attachment_ref"] == cam_sha
    assert outcome["source"] == "camera"
    assert outcome["sources"] == ["camera", "screen"]


@pytest.mark.asyncio
async def test_a_single_source_frame_still_records_one_ref(tmp_path: Path) -> None:
    """The non-fused path is the common one and must not change shape."""
    episode, cam_sha, scr_sha = await _run_fused_frame(tmp_path, fused=False)
    outcome = episode.outcomes[0]

    assert outcome["attachment_ref"] == cam_sha
    assert outcome["attachment_refs"] == [cam_sha]
    recorded = _all_strings(episode)
    assert cam_sha in recorded, "premise: this frame's own ref is missing"
    assert scr_sha not in recorded, (
        "a frame that was never part of this observation was recorded anyway"
    )


# ── the chain ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_erasing_a_fused_episode_unlinks_both_frames(tmp_path: Path) -> None:
    """producer -> episode -> ErasureManager, in one test.

    A test that the producer records both refs, and a separate test that the
    extractor reads the key, can BOTH pass while the chain is dead -- the
    episode carries the list under a name the extractor never consults. This
    spans the seam, driving the real ``ErasureManager`` over the episode the
    real consumer actually produced.
    """
    episode, cam_sha, scr_sha = await _run_fused_frame(tmp_path, fused=True)

    store = await _erase(episode)

    assert cam_sha in store.deleted
    assert scr_sha in store.deleted, (
        "the second bound frame survived an explicit erasure and is now "
        "orphaned -- no episode points at it"
    )


# ── extractor ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_extractor_reads_the_refs_list() -> None:
    """``attachment_refs`` is a declared field erasure consults."""
    episode = Episode(
        user_input="",
        outcomes=[{"intent": "vision_observation", "attachment_refs": [_CAM, _SCR]}],
    )
    store = await _erase(episode)
    assert store.deleted == {_CAM, _SCR}


@pytest.mark.asyncio
async def test_a_malformed_refs_entry_does_not_block_the_others() -> None:
    """One bad id must not cost the erasure of its siblings."""
    episode = Episode(
        user_input="",
        outcomes=[
            {
                "intent": "vision_observation",
                "attachment_refs": [_CAM, "not-a-sha", 17, None, _SCR],
            }
        ],
    )
    store = await _erase(episode)
    assert store.deleted == {_CAM, _SCR}
