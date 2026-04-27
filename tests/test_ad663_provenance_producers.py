"""AD-663: Provenance Producer Wiring."""

from __future__ import annotations

import hashlib

from probos.cognitive.social_verification import _share_artifact_ancestry
from probos.types import AnchorFrame, Episode
from probos.ward_room.models import WardRoomPost, WardRoomThread


def _artifact_version(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _assert_artifact_version(artifact_version: str, expected_input: str) -> None:
    assert len(artifact_version) == 16
    assert all(char in "0123456789abcdef" for char in artifact_version)
    assert artifact_version == hashlib.sha256(expected_input.encode("utf-8")).hexdigest()[:16]


def _reply_anchor(post: WardRoomPost, body: str) -> AnchorFrame:
    return AnchorFrame(
        channel="ward_room",
        channel_id="science",
        thread_id=post.thread_id,
        trigger_type="ward_room_reply",
        participants=[post.author_callsign or post.author_id],
        trigger_agent=post.author_callsign or post.author_id,
        department="science",
        source_timestamp=post.created_at,
        source_origin_id=f"wr-post:{post.id}",
        artifact_version=_artifact_version(body or ""),
    )


def _thread_anchor(thread: WardRoomThread, title: str) -> AnchorFrame:
    return AnchorFrame(
        channel="ward_room",
        channel_id=thread.channel_id,
        thread_id=thread.id,
        trigger_type="ward_room_post",
        participants=[thread.author_callsign or thread.author_id],
        trigger_agent=thread.author_callsign or thread.author_id,
        department="science",
        source_timestamp=thread.created_at,
        source_origin_id=f"wr-thread:{thread.id}",
        artifact_version=_artifact_version(title or ""),
    )


def _proactive_provenance(ward_room_activity: list[dict[str, str]]) -> tuple[str, str]:
    wr_origin = ""
    wr_version = ""
    if ward_room_activity:
        first_post_id = ward_room_activity[0].get("post_id", "") if ward_room_activity else ""
        if first_post_id:
            wr_origin = f"wr-post:{first_post_id}"
        post_ids = sorted(
            activity.get("post_id", "")
            for activity in ward_room_activity
            if activity.get("post_id")
        )
        if post_ids:
            wr_version = _artifact_version("|".join(post_ids))
    return wr_origin, wr_version


def _proactive_anchor(ward_room_activity: list[dict[str, str]]) -> AnchorFrame:
    source_origin_id, artifact_version = _proactive_provenance(ward_room_activity)
    return AnchorFrame(
        channel="duty_report",
        duty_cycle_id="duty-123",
        department="science",
        trigger_type="duty_cycle",
        source_origin_id=source_origin_id,
        artifact_version=artifact_version,
    )


def _action_anchor(observation: dict[str, str], query_text: object) -> AnchorFrame:
    return AnchorFrame(
        channel="action",
        department="science",
        trigger_type="proactive_think",
        trigger_agent="Atlas",
        source_origin_id=observation.get("correlation_id", "") or "",
        artifact_version=_artifact_version(str(query_text)[:500]),
    )


def test_wr_reply_episode_has_provenance() -> None:
    post = WardRoomPost(
        id="post-123",
        thread_id="thread-1",
        parent_id=None,
        author_id="agent-1",
        body="The relay telemetry is stable.",
        created_at=1712500000.0,
        author_callsign="Atlas",
    )

    anchors = _reply_anchor(post, post.body)

    assert anchors.source_origin_id == f"wr-post:{post.id}"
    _assert_artifact_version(anchors.artifact_version, post.body)


def test_wr_thread_episode_has_provenance() -> None:
    thread = WardRoomThread(
        id="thread-123",
        channel_id="ch-science",
        author_id="agent-1",
        title="Plasma relay status",
        body="Opening report",
        created_at=1712500000.0,
        last_activity=1712500000.0,
        author_callsign="Atlas",
    )

    anchors = _thread_anchor(thread, thread.title)

    assert anchors.source_origin_id == f"wr-thread:{thread.id}"
    _assert_artifact_version(anchors.artifact_version, thread.title)


def test_wr_same_post_same_provenance() -> None:
    post = WardRoomPost(
        id="post-123",
        thread_id="thread-1",
        parent_id=None,
        author_id="agent-1",
        body="The same observation.",
        created_at=1712500000.0,
    )

    first_anchor = _reply_anchor(post, post.body)
    second_anchor = _reply_anchor(post, post.body)

    assert first_anchor.source_origin_id == second_anchor.source_origin_id
    assert first_anchor.artifact_version == second_anchor.artifact_version


def test_wr_edited_post_different_version() -> None:
    original_post = WardRoomPost(
        id="post-123",
        thread_id="thread-1",
        parent_id=None,
        author_id="agent-1",
        body="Original observation.",
        created_at=1712500000.0,
    )
    edited_post = WardRoomPost(
        id="post-123",
        thread_id="thread-1",
        parent_id=None,
        author_id="agent-1",
        body="Edited observation.",
        created_at=1712500000.0,
    )

    original_anchor = _reply_anchor(original_post, original_post.body)
    edited_anchor = _reply_anchor(edited_post, edited_post.body)

    assert original_anchor.source_origin_id == edited_anchor.source_origin_id
    assert original_anchor.artifact_version != edited_anchor.artifact_version


def test_proactive_episode_has_wr_provenance() -> None:
    post_id = "post-123"
    anchors = _proactive_anchor([{"post_id": post_id}])

    assert anchors.source_origin_id == f"wr-post:{post_id}"
    _assert_artifact_version(anchors.artifact_version, post_id)


def test_proactive_same_activity_same_provenance() -> None:
    activity = [{"post_id": "post-x"}, {"post_id": "post-y"}]

    first_anchor = _proactive_anchor(activity)
    second_anchor = _proactive_anchor(activity)

    assert first_anchor.source_origin_id == second_anchor.source_origin_id
    assert first_anchor.artifact_version == second_anchor.artifact_version


def test_proactive_subset_activity_different_version() -> None:
    full_activity = [
        {"post_id": "post-x"},
        {"post_id": "post-y"},
        {"post_id": "post-z"},
    ]
    subset_activity = [{"post_id": "post-x"}, {"post_id": "post-y"}]

    full_anchor = _proactive_anchor(full_activity)
    subset_anchor = _proactive_anchor(subset_activity)

    assert full_anchor.source_origin_id == subset_anchor.source_origin_id
    assert full_anchor.artifact_version != subset_anchor.artifact_version


def test_proactive_empty_activity_no_provenance() -> None:
    anchors = _proactive_anchor([])

    assert anchors.source_origin_id == ""
    assert anchors.artifact_version == ""


def test_action_episode_correlation_id_provenance() -> None:
    query_text = "Analyze the new Ward Room report."
    anchors = _action_anchor({"correlation_id": "evt-123"}, query_text)

    assert anchors.source_origin_id == "evt-123"
    _assert_artifact_version(anchors.artifact_version, query_text)


def test_action_episode_no_correlation_id() -> None:
    anchors = _action_anchor({}, "Analyze the new Ward Room report.")

    assert anchors.source_origin_id == ""


def test_shared_ancestry_detected_for_same_wr_post() -> None:
    body = "Shared report body."
    episode_alpha = Episode(
        user_input="alpha",
        anchors=AnchorFrame(
            source_origin_id="wr-post:post-123",
            artifact_version=_artifact_version(body),
        ),
    )
    episode_beta = Episode(
        user_input="beta",
        anchors=AnchorFrame(
            source_origin_id="wr-post:post-123",
            artifact_version=_artifact_version(body),
        ),
    )

    assert episode_alpha.anchors is not None
    assert episode_beta.anchors is not None
    _assert_artifact_version(episode_alpha.anchors.artifact_version, body)
    assert _share_artifact_ancestry(episode_alpha.anchors, episode_beta.anchors) is True


def test_no_shared_ancestry_for_different_posts() -> None:
    episode_alpha = Episode(
        user_input="alpha",
        anchors=AnchorFrame(source_origin_id="wr-post:post-123"),
    )
    episode_beta = Episode(
        user_input="beta",
        anchors=AnchorFrame(source_origin_id="wr-post:post-456"),
    )

    assert episode_alpha.anchors is not None
    assert episode_beta.anchors is not None
    assert _share_artifact_ancestry(episode_alpha.anchors, episode_beta.anchors) is False


def test_provenance_prefix_prevents_cross_type_collision() -> None:
    post_episode = Episode(
        user_input="post",
        anchors=AnchorFrame(source_origin_id="wr-post:abc-123"),
    )
    thread_episode = Episode(
        user_input="thread",
        anchors=AnchorFrame(source_origin_id="wr-thread:abc-123"),
    )
    control_episode = Episode(
        user_input="control",
        anchors=AnchorFrame(source_origin_id="wr-post:abc-123"),
    )

    assert post_episode.anchors is not None
    assert thread_episode.anchors is not None
    assert control_episode.anchors is not None
    # Without the type prefix, both origins would be "abc-123" and share ancestry.
    # The prefix keeps WR posts and threads with the same UUID distinct artifacts.
    assert _share_artifact_ancestry(post_episode.anchors, thread_episode.anchors) is False
    assert _share_artifact_ancestry(post_episode.anchors, control_episode.anchors) is True
