"""AD-719a: multi-agent WardRoom thread contract tests."""
from __future__ import annotations

import inspect
from typing import Any

import pytest

from probos.ward_room import multi_agent as ma
from probos.ward_room.multi_agent import (
    MULTI_AGENT_THREAD_MODE,
    create_multi_agent_thread,
    cross_agent_visibility,
    format_participant_trailer,
    is_participant,
    parse_participants,
)
from probos.ward_room.models import WardRoomThread


class _FakeWardRoomService:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    async def create_thread(
        self,
        *,
        channel_id: str,
        author_id: str,
        title: str,
        body: str,
        author_callsign: str = "",
        thread_mode: str = "discuss",
        max_responders: int = 0,
    ) -> WardRoomThread:
        record = {
            "channel_id": channel_id, "author_id": author_id,
            "title": title, "body": body,
            "author_callsign": author_callsign,
            "thread_mode": thread_mode,
            "max_responders": max_responders,
        }
        self.created.append(record)
        import time
        return WardRoomThread(
            id=f"thread-{len(self.created)}",
            channel_id=channel_id,
            author_id=author_id,
            title=title,
            body=body,
            created_at=time.time(),
            last_activity=time.time(),
            thread_mode=thread_mode,
            author_callsign=author_callsign,
            max_responders=max_responders,
        )


# 1. create_multi_agent_thread creates a thread with thread_mode='multi_agent'.
@pytest.mark.asyncio
async def test_create_multi_agent_thread_marks_thread_mode() -> None:
    service = _FakeWardRoomService()
    thread = await create_multi_agent_thread(
        service,
        channel_id="ch1",
        captain_id="captain",
        title="Plan the briefing",
        body="What do we need?",
        mentioned_agent_ids=["maya", "ezri"],
    )
    assert thread.thread_mode == MULTI_AGENT_THREAD_MODE
    assert service.created[0]["thread_mode"] == "multi_agent"
    assert service.created[0]["author_id"] == "captain"


# 2. Captain is the seeded author (Wave 163 architectural decision).
@pytest.mark.asyncio
async def test_multi_agent_thread_captain_is_author() -> None:
    service = _FakeWardRoomService()
    thread = await create_multi_agent_thread(
        service,
        channel_id="ch1",
        captain_id="captain",
        title="Plan",
        body="briefing",
        mentioned_agent_ids=["maya"],
        captain_callsign="Captain",
    )
    assert thread.author_id == "captain"
    assert thread.author_callsign == "Captain"


# 3. Participants trailer encoded in body; parse_participants recovers it.
@pytest.mark.asyncio
async def test_participants_trailer_roundtrip() -> None:
    service = _FakeWardRoomService()
    thread = await create_multi_agent_thread(
        service,
        channel_id="ch1",
        captain_id="captain",
        title="x",
        body="initial body",
        mentioned_agent_ids=["maya", "ezri", "scotty"],
    )
    recovered = parse_participants(thread.body)
    assert recovered == ["maya", "ezri", "scotty"]


# 4. Cross-agent visibility: declared participant gets True; non-participant False.
def test_cross_agent_visibility_within_thread_yes_cross_thread_no() -> None:
    body = "How should we proceed?\n\n@participants: maya,ezri"
    # Maya is a declared participant -> may observe.
    assert cross_agent_visibility(
        thread_body=body, post_authors=[], agent_id="maya",
    ) is True
    # Bones was never @-mentioned and never posted -> may NOT observe.
    assert cross_agent_visibility(
        thread_body=body, post_authors=[], agent_id="bones",
    ) is False


# 5. is_participant: post authorship also confers participant status.
def test_is_participant_post_authorship() -> None:
    body = "x\n\n@participants: maya"
    # Bones authored a post (was @-mentioned in a subsequent turn that
    # mutated participants) -> participant.
    assert is_participant(
        thread_body=body, post_authors=["bones"], agent_id="bones",
    ) is True


# 6. AD-731 invariant: module never inlines image bytes.
def test_ad731_invariant_no_inline_image_bytes() -> None:
    source = inspect.getsource(ma)
    assert "b64encode" not in source
    assert "base64.b64" not in source
    # Module operates on textual thread bodies + agent_id lists only.
    assert "image_url" not in source
