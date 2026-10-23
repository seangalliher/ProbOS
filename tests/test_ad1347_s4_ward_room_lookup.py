"""AD-1347 S4 (#1627) M1: a Ward Room thread or post by id, live or in the prune archive.

A real ``WardRoomService`` over SQLite in ``tmp_path``. Archive files are written by the real
``prune_old_threads`` unless a test needs a record the writer cannot make (a shared id prefix,
an oversized or torn line); those lines use the writer's shape (``_archive_line``), and
``test_the_writer_and_the_scanner_agree_on_the_record_shape`` pins that agreement.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from probos.config_models.crew import WardRoomConfig
from probos.visiting_officers import VISITING_AGENT_TYPE
from probos.ward_room import lookup as lookup_module
from probos.ward_room.lookup import (
    KIND_POST,
    KIND_THREAD,
    LOOKUP_AMBIGUOUS,
    LOOKUP_FOUND,
    LOOKUP_INVALID_REF,
    LOOKUP_NOT_FOUND,
    LOOKUP_REFUSED,
    MAX_BODY_CHARS,
    MAX_POSTS_SHOWN,
    MAX_RENDER_CHARS,
    SOURCE_ARCHIVE,
    SOURCE_LIVE,
    render_lookup,
)
from probos.ward_room.service import WardRoomService

FORGE = "forge-1"  # Engineering member
LAFORGE = "laforge-1"  # Engineering member
CHAPEL = "chapel-1"  # Medical member only
WORF = "worf-1"  # a member of no channel
MONTH = "ward_room_archive_2026-10.jsonl"


class _Cert:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type


class _Identities:
    """The two identity reads the lookup makes: BF-907's ``resolve_slot_id`` and BF-903's ``get_by_uuid``."""

    def __init__(self, slots: dict[str, str], visitors: frozenset[str] = frozenset()) -> None:
        self._slots = slots
        self._visitors = visitors

    def resolve_slot_id(self, identity: str) -> str | None:
        return self._slots.get(identity)

    def get_by_uuid(self, agent_uuid: str) -> Any:
        return _Cert(VISITING_AGENT_TYPE) if agent_uuid in self._visitors else None


_STARTED: list[Any] = []


@pytest.fixture(autouse=True)
async def _stop_started_services() -> AsyncIterator[None]:
    """A failed assertion skips the test's own ``stop()``, and an open connection keeps the interpreter from exiting."""
    yield
    while _STARTED:
        await _STARTED.pop().stop()


async def _ward_room(tmp_path: Path, identities: Any = None) -> Any:
    """A started service: FORGE and LAFORGE in Engineering, CHAPEL in Medical (AD-621 memberships).

    Returned as ``Any`` on purpose: the phantom precheck types a name bound by a constructor call.
    """
    started = WardRoomService(db_path=str(tmp_path / "wr.db"), identity_registry=identities)
    await started.start()
    _STARTED.append(started)
    engineering = await started.get_channel_by_department("engineering")
    medical = await started.get_channel_by_department("medical")
    for agent_id in (FORGE, LAFORGE):
        await started.subscribe(agent_id, engineering.id)
    await started.subscribe(CHAPEL, medical.id)
    return started


async def _attach_archive(wr: Any, archive: Path) -> None:
    """The production wiring: ``start_prune_loop`` names the directory; the loop sleeps first, so nothing is pruned."""
    await wr.start_prune_loop(WardRoomConfig(prune_interval_seconds=3600.0), archive)
    await wr.stop_prune_loop()


async def _prune_all(wr: Any, archive: Path) -> None:
    """AD-416's real prune into one monthly file: a negative retention reaches every eligible thread (all the fixtures' are; a Captain-authored one can be kept)."""
    await wr.prune_old_threads(retention_days=-1, retention_days_endorsed=-1, archive_path=str(archive / MONTH))


def _archive_line(thread_id: str, channel_id: str, *, body: str = "archived body") -> str:
    """One record in the writer's shape (``ThreadManager.prune_old_threads``, ``json.dumps`` defaults)."""
    return json.dumps({
        "thread_id": thread_id, "channel_id": channel_id, "author_id": FORGE,
        "author_callsign": "Forge", "title": f"Title {thread_id[:8]}", "body": body,
        "created_at": 1760000000.0, "last_activity": 1760000000.0, "thread_mode": "discuss",
        "net_score": 0, "reply_count": 0, "posts": [], "pruned_at": 1760600000.0,
    }) + "\n"


async def test_a_member_finds_a_live_thread_by_its_eight_character_prefix(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    engineering = await wr.get_channel_by_department("engineering")
    thread = await wr.create_thread(engineering.id, FORGE, "Plasma relay", "Relay 4 is at 93 percent.", author_callsign="Forge")
    await wr.create_post(thread.id, LAFORGE, "Confirmed on my console.", author_callsign="LaForge")

    for ref in (thread.id[:8], thread.id, f"#{thread.id[:8].upper()}"):
        result = await wr.lookup_record(LAFORGE, ref)
        assert result.outcome == LOOKUP_FOUND, ref
        found = result.matches[0].candidate
        assert (found.kind, found.source, found.thread_id) == (KIND_THREAD, SOURCE_LIVE, thread.id)
    text = render_lookup(result)
    assert "Relay 4 is at 93 percent." in text and "Confirmed on my console." in text
    assert "#Engineering" in text and "the live Ward Room" in text
    await wr.stop()


async def test_a_pruned_thread_is_found_in_the_archive_the_prune_wrote(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    archive = tmp_path / "ward_room_archive"
    await _attach_archive(wr, archive)
    engineering = await wr.get_channel_by_department("engineering")
    thread = await wr.create_thread(engineering.id, FORGE, "The 51d91a7d case", "The original claim.", author_callsign="Forge")
    await wr.create_post(thread.id, LAFORGE, "A reply that was later pruned.", author_callsign="LaForge")
    await _prune_all(wr, archive)
    assert await wr.get_thread(thread.id) is None, "premise: the live Ward Room no longer has it"

    result = await wr.lookup_record(FORGE, thread.id[:8])

    assert result.outcome == LOOKUP_FOUND and result.complete
    found = result.matches[0].candidate
    assert (found.kind, found.source, found.post_count) == (KIND_THREAD, SOURCE_ARCHIVE, 1)
    text = render_lookup(result)
    assert "The original claim." in text and "A reply that was later pruned." in text
    assert "the Ward Room archive (pruned " in text
    await wr.stop()


async def test_the_writer_and_the_scanner_agree_on_the_record_shape(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    archive = tmp_path / "ward_room_archive"
    engineering = await wr.get_channel_by_department("engineering")
    thread = await wr.create_thread(engineering.id, FORGE, "Shape", "body", author_callsign="Forge")
    post = await wr.create_post(thread.id, LAFORGE, "reply", author_callsign="LaForge")
    await _prune_all(wr, archive)

    written = (archive / MONTH).read_text(encoding="utf-8")

    assert f'"thread_id": "{thread.id}"' in written, "the scanner's thread prefilter"
    assert f'"id": "{post.id}"' in written, "the scanner's post prefilter"
    assert written.count("\n") == 1, "one record per thread, its posts nested"
    await wr.stop()


async def test_a_post_is_found_by_its_own_id_live_and_archived(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    archive = tmp_path / "ward_room_archive"
    await _attach_archive(wr, archive)
    engineering = await wr.get_channel_by_department("engineering")
    thread = await wr.create_thread(engineering.id, FORGE, "Posts", "opening", author_callsign="Forge")
    post = await wr.create_post(thread.id, LAFORGE, "The post Chapel asked about.", author_callsign="LaForge")

    live = await wr.lookup_record(FORGE, post.id[:8])
    assert live.outcome == LOOKUP_FOUND
    assert (live.matches[0].candidate.kind, live.matches[0].candidate.matched_post_id) == (KIND_POST, post.id)

    await _prune_all(wr, archive)
    archived = await wr.lookup_record(FORGE, post.id[:8])
    assert archived.outcome == LOOKUP_FOUND
    found = archived.matches[0].candidate
    assert (found.kind, found.source, found.matched_post_id) == (KIND_POST, SOURCE_ARCHIVE, post.id)
    assert "The post Chapel asked about." in render_lookup(archived)
    await wr.stop()


async def test_a_department_thread_is_invisible_outside_its_members_and_reads_as_absent(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    archive = tmp_path / "ward_room_archive"
    await _attach_archive(wr, archive)
    engineering = await wr.get_channel_by_department("engineering")
    thread = await wr.create_thread(engineering.id, FORGE, "Engineering only", "warp core notes", author_callsign="Forge")
    ref = thread.id[:8]
    absent_ref = "abcd0123" if ref == "0123abcd" else "0123abcd"

    for stage in ("live", "archived"):
        if stage == "archived":
            await _prune_all(wr, archive)
        for outsider in (CHAPEL, WORF):
            hidden = await wr.lookup_record(outsider, ref)
            absent = await wr.lookup_record(outsider, absent_ref)
            assert (hidden.outcome, hidden.matches, hidden.complete) == (LOOKUP_NOT_FOUND, (), True), (stage, outsider)
            assert (absent.outcome, absent.matches, absent.complete) == (LOOKUP_NOT_FOUND, (), True), (stage, outsider)
            assert render_lookup(hidden).replace(ref, "<id>") == render_lookup(absent).replace(absent_ref, "<id>")
        assert (await wr.lookup_record(LAFORGE, ref)).outcome == LOOKUP_FOUND, stage
    await wr.stop()


async def test_a_dm_thread_is_visible_to_its_participants_only_live_archived_and_after_dm_archival(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    archive = tmp_path / "ward_room_archive"
    await _attach_archive(wr, archive)
    dm = await wr.get_or_create_dm_channel(FORGE, CHAPEL, "Forge", "Chapel")
    thread = await wr.create_thread(dm.id, FORGE, "[DM]", "Private: my readings are off.", author_callsign="Forge")
    await wr.create_post(thread.id, CHAPEL, "Private reply.", author_callsign="Chapel")
    ref = thread.id[:8]
    assert await wr.archive_dm_messages(max_age_hours=-1) == 1, "premise: AD-485 flags it; the row stays"

    for stage in ("flagged archived", "pruned"):
        if stage == "pruned":
            await _prune_all(wr, archive)
        for participant in (FORGE, CHAPEL):
            assert (await wr.lookup_record(participant, ref)).outcome == LOOKUP_FOUND, (stage, participant)
        for outsider in (LAFORGE, WORF):
            assert (await wr.lookup_record(outsider, ref)).outcome == LOOKUP_NOT_FOUND, (stage, outsider)
    await wr.stop()


async def test_an_author_in_a_captain_dm_channel_with_no_membership_rows_sees_its_own_thread(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    channel = await wr.create_channel(f"dm-captain-{FORGE[:8]}", "dm", FORGE, description="DM: Forge to Captain")
    assert await wr.get_channel_subscriber_ids(channel.id) == set(), "premise: AD-485's Captain DM channel has no members"
    thread = await wr.create_thread(channel.id, FORGE, "[DM to Captain from @Forge]", "Please check thread 51d91a7d.", author_callsign="Forge")
    await wr.create_post(thread.id, "captain", "Checked: it was pruned.", author_callsign="Captain")
    ref = thread.id[:8]

    assert (await wr.lookup_record(FORGE, ref)).outcome == LOOKUP_FOUND
    for outsider in (LAFORGE, CHAPEL):
        assert (await wr.lookup_record(outsider, ref)).outcome == LOOKUP_NOT_FOUND, outsider
    await wr.stop()


async def test_authoring_a_post_does_not_open_a_department_channel(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    engineering = await wr.get_channel_by_department("engineering")
    thread = await wr.create_thread(engineering.id, FORGE, "Engineering", "core", author_callsign="Forge")
    await wr.create_post(thread.id, WORF, "Security note.", author_callsign="Worf")

    assert (await wr.lookup_record(WORF, thread.id[:8])).outcome == LOOKUP_NOT_FOUND
    await wr.stop()


@pytest.mark.parametrize("requester", ["", "   ", None, 42])
async def test_an_unidentified_requester_is_refused_before_any_read(tmp_path: Path, requester: Any) -> None:
    wr = await _ward_room(tmp_path)
    engineering = await wr.get_channel_by_department("engineering")
    thread = await wr.create_thread(engineering.id, FORGE, "t", "b", author_callsign="Forge")

    result = await wr.lookup_record(requester, thread.id[:8])

    assert (result.outcome, result.matches) == (LOOKUP_REFUSED, ())
    assert render_lookup(result) == "The Ward Room lookup could not confirm who is asking, so it returned nothing."
    await wr.stop()


async def test_a_sovereign_id_resolves_to_its_slot_and_an_unresolved_or_visiting_one_is_refused(tmp_path: Path) -> None:
    resolved, unresolved, visitor = (str(uuid.uuid4()) for _ in range(3))
    wr = await _ward_room(tmp_path, _Identities({resolved: FORGE, visitor: FORGE}, frozenset({visitor})))
    engineering = await wr.get_channel_by_department("engineering")
    thread = await wr.create_thread(engineering.id, FORGE, "t", "b", author_callsign="Forge")
    ref = thread.id[:8]

    assert (await wr.lookup_record(resolved, ref)).outcome == LOOKUP_FOUND
    assert (await wr.lookup_record(unresolved, ref)).outcome == LOOKUP_REFUSED
    assert (await wr.lookup_record(visitor, ref)).outcome == LOOKUP_REFUSED, "a visitor is refused even when a slot maps"
    assert (await wr.lookup_record("captain", ref)).outcome == LOOKUP_NOT_FOUND, "the Captain's key is no member: no fallback"
    await wr.stop()


@pytest.mark.parametrize("ref", ["51d91a7", "thread 51d91a7d", "zzzzzzzz", "51d91a7d" + "0" * 29, "", None])
async def test_a_ref_that_is_not_8_to_36_id_characters_is_invalid(tmp_path: Path, ref: Any) -> None:
    wr = await _ward_room(tmp_path)

    result = await wr.lookup_record(FORGE, ref)

    assert (result.outcome, result.matches) == (LOOKUP_INVALID_REF, ())
    assert "is not a Ward Room id" in render_lookup(result)
    await wr.stop()


async def test_only_visible_records_count_toward_a_match_or_an_ambiguity(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    archive = tmp_path / "ward_room_archive"
    await _attach_archive(wr, archive)
    engineering = await wr.get_channel_by_department("engineering")
    medical = await wr.get_channel_by_department("medical")
    archive.mkdir(parents=True, exist_ok=True)
    (archive / MONTH).write_text(
        _archive_line("abcdef01-0000-4000-8000-00000000000a", engineering.id)
        + _archive_line("abcdef01-0000-4000-8000-00000000000b", engineering.id)
        + _archive_line("abcdef02-0000-4000-8000-00000000000a", engineering.id, body="engineering record")
        + _archive_line("abcdef02-0000-4000-8000-00000000000b", medical.id, body="medical record"),
        encoding="utf-8",
    )

    both = await wr.lookup_record(FORGE, "abcdef01")
    assert both.outcome == LOOKUP_AMBIGUOUS and len(both.matches) == 2
    assert "abcdef01-0000-4000-8000-00000000000a" in render_lookup(both)
    forge = await wr.lookup_record(FORGE, "abcdef02")
    chapel = await wr.lookup_record(CHAPEL, "abcdef02")
    assert forge.outcome == LOOKUP_FOUND and chapel.outcome == LOOKUP_FOUND
    assert "engineering record" in render_lookup(forge) and "medical record" not in render_lookup(forge)
    assert "medical record" in render_lookup(chapel)
    assert (await wr.lookup_record(WORF, "abcdef02")).outcome == LOOKUP_NOT_FOUND
    await wr.stop()


async def test_the_scan_reads_the_newest_twelve_months_and_says_when_it_stopped(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    archive = tmp_path / "ward_room_archive"
    await _attach_archive(wr, archive)
    engineering = await wr.get_channel_by_department("engineering")
    archive.mkdir(parents=True, exist_ok=True)
    months = [f"{2025 + (9 + i) // 12}-{(9 + i) % 12 + 1:02d}" for i in range(13)]  # 2025-10 .. 2026-10
    for i, month in enumerate(months):
        (archive / f"ward_room_archive_{month}.jsonl").write_text(
            _archive_line(f"aa{i:06x}-0000-4000-8000-000000000000", engineering.id, body=f"record of {month}"),
            encoding="utf-8",
        )

    newest = await wr.lookup_record(FORGE, "aa00000c")  # 2026-10
    oldest = await wr.lookup_record(FORGE, "aa000000")  # 2025-10, the thirteenth newest

    assert newest.outcome == LOOKUP_FOUND and not newest.complete
    assert "record of 2026-10" in render_lookup(newest)
    assert (oldest.outcome, oldest.complete) == (LOOKUP_NOT_FOUND, False)
    assert "stopped at a size limit" in render_lookup(oldest)
    await wr.stop()


async def test_an_oversized_or_torn_record_is_skipped_and_marks_the_scan_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lookup_module, "MAX_LINE_BYTES", 1024)
    wr = await _ward_room(tmp_path)
    archive = tmp_path / "ward_room_archive"
    await _attach_archive(wr, archive)
    engineering = await wr.get_channel_by_department("engineering")
    archive.mkdir(parents=True, exist_ok=True)
    torn = _archive_line("bb000002-0000-4000-8000-000000000002", engineering.id)[:60] + "\n"
    (archive / MONTH).write_text(
        _archive_line("bb000001-0000-4000-8000-000000000001", engineering.id, body="x" * 4000)
        + torn
        + _archive_line("bb000003-0000-4000-8000-000000000003", engineering.id, body="after the bad lines"),
        encoding="utf-8",
    )

    for ref in ("bb000001", "bb000002"):
        result = await wr.lookup_record(FORGE, ref)
        assert (result.outcome, result.complete) == (LOOKUP_NOT_FOUND, False), ref
    after = await wr.lookup_record(FORGE, "bb000003")
    assert after.outcome == LOOKUP_FOUND
    assert after.complete is False, "an oversized record anywhere means the scan cannot vouch for it"
    assert "after the bad lines" in render_lookup(after)
    await wr.stop()


async def test_the_byte_budget_stops_the_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wr = await _ward_room(tmp_path)
    archive = tmp_path / "ward_room_archive"
    await _attach_archive(wr, archive)
    engineering = await wr.get_channel_by_department("engineering")
    archive.mkdir(parents=True, exist_ok=True)
    filler = json.dumps({"note": "f" * 400}) + "\n"
    (archive / MONTH).write_text(
        filler + _archive_line("cc000001-0000-4000-8000-000000000001", engineering.id), encoding="utf-8",
    )

    monkeypatch.setattr(lookup_module, "MAX_ARCHIVE_BYTES", 256)
    stopped = await wr.lookup_record(FORGE, "cc000001")
    assert (stopped.outcome, stopped.complete) == (LOOKUP_NOT_FOUND, False)
    monkeypatch.setattr(lookup_module, "MAX_ARCHIVE_BYTES", 64 * 1024 * 1024)
    assert (await wr.lookup_record(FORGE, "cc000001")).outcome == LOOKUP_FOUND
    await wr.stop()


async def test_without_a_known_archive_directory_a_not_found_says_the_search_was_incomplete(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)

    unknown = await wr.lookup_record(FORGE, "dd000001")
    assert (unknown.outcome, unknown.complete) == (LOOKUP_NOT_FOUND, False)
    assert "stopped at a size limit" in render_lookup(unknown)

    await _attach_archive(wr, tmp_path / "never-written")
    empty = await wr.lookup_record(FORGE, "dd000001")
    assert (empty.outcome, empty.complete) == (LOOKUP_NOT_FOUND, True), "a directory nothing was pruned into is empty"
    await wr.stop()


async def test_a_record_in_an_unknown_channel_is_visible_to_no_one(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    archive = tmp_path / "ward_room_archive"
    await _attach_archive(wr, archive)
    archive.mkdir(parents=True, exist_ok=True)
    (archive / MONTH).write_text(
        _archive_line("ee000001-0000-4000-8000-000000000001", "no-such-channel"), encoding="utf-8",
    )

    for asker in (FORGE, CHAPEL, WORF):
        assert (await wr.lookup_record(asker, "ee000001")).outcome == LOOKUP_NOT_FOUND, asker
    await wr.stop()


async def test_a_long_thread_renders_its_last_posts_within_the_character_cap(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    engineering = await wr.get_channel_by_department("engineering")
    thread = await wr.create_thread(engineering.id, FORGE, "Long", "start", author_callsign="Forge")
    for n in range(30):
        await wr.create_post(thread.id, LAFORGE, f"post {n:02d} " + "y" * 600, author_callsign="LaForge")

    result = await wr.lookup_record(FORGE, thread.id[:8])

    found = result.matches[0].candidate
    assert (found.post_count, len(found.posts)) == (30, MAX_POSTS_SHOWN)
    text = render_lookup(result)
    assert len(text) <= MAX_RENDER_CHARS
    assert "30 replies; the last 12:" in text
    assert all(len(line) <= MAX_BODY_CHARS + 80 for line in text.splitlines())
    await wr.stop()


async def test_a_post_flagged_deleted_shows_the_flag_and_reason_never_its_body(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    engineering = await wr.get_channel_by_department("engineering")
    thread = await wr.create_thread(engineering.id, FORGE, "Moderated", "opening", author_callsign="Forge")
    post = await wr.create_post(thread.id, LAFORGE, "The words that were removed.", author_callsign="LaForge")
    connection = sqlite3.connect(str(tmp_path / "wr.db"))
    try:  # no code path writes posts.deleted today (Absence AV2); the column is what is rendered
        connection.execute(
            "UPDATE posts SET deleted = 1, delete_reason = ? WHERE id = ?", ("moderated by the Captain", post.id),
        )
        connection.commit()
    finally:
        connection.close()

    for ref in (post.id[:8], thread.id[:8]):
        text = render_lookup(await wr.lookup_record(FORGE, ref))
        assert "[deleted: moderated by the Captain]" in text, ref
        assert "The words that were removed." not in text, ref
    await wr.stop()


async def test_hidden_archived_records_sharing_a_prefix_change_nothing_a_non_member_sees(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    archive = tmp_path / "ward_room_archive"
    await _attach_archive(wr, archive)
    engineering = await wr.get_channel_by_department("engineering")
    medical = await wr.get_channel_by_department("medical")
    archive.mkdir(parents=True, exist_ok=True)
    hidden_lines = "".join(
        _archive_line(f"abcdef{prefix}-0000-4000-8000-00000000000{n}", medical.id)
        for prefix in ("03", "05") for n in range(4)
    )
    (archive / MONTH).write_text(
        hidden_lines + _archive_line("abcdef05-0000-4000-8000-0000000000ff", engineering.id, body="the visible one"),
        encoding="utf-8",
    )
    assert (await wr.lookup_record(CHAPEL, "abcdef03")).outcome == LOOKUP_AMBIGUOUS, "premise: a member sees the four"

    hidden = await wr.lookup_record(FORGE, "abcdef03")
    absent = await wr.lookup_record(FORGE, "abcdef04")
    assert (hidden.outcome, hidden.matches, hidden.complete) == (LOOKUP_NOT_FOUND, (), True)
    assert (absent.outcome, absent.matches, absent.complete) == (LOOKUP_NOT_FOUND, (), True)
    assert render_lookup(hidden).replace("abcdef03", "<id>") == render_lookup(absent).replace("abcdef04", "<id>")
    crowded = await wr.lookup_record(FORGE, "abcdef05")
    assert (crowded.outcome, crowded.complete) == (LOOKUP_FOUND, True), "four hidden records come before it"
    assert "the visible one" in render_lookup(crowded)
    await wr.stop()


async def test_hidden_live_threads_sharing_a_prefix_do_not_crowd_out_a_visible_one(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    await _attach_archive(wr, tmp_path / "never-written")
    engineering = await wr.get_channel_by_department("engineering")
    medical = await wr.get_channel_by_department("medical")
    made = [await wr.create_thread(medical.id, CHAPEL, f"Medical {n}", "sickbay", author_callsign="Chapel") for n in range(4)]
    made.append(await wr.create_thread(engineering.id, FORGE, "Engineering", "the visible one", author_callsign="Forge"))
    crafted = [f"abcdef06-0000-4000-8000-00000000000{n}" for n in range(4)] + ["abcdef06-0000-4000-8000-0000000000ff"]
    connection = sqlite3.connect(str(tmp_path / "wr.db"))
    try:  # the service makes uuid4 ids; a shared prefix needs an import or a hand edit, as here
        for thread, crafted_id in zip(made, crafted):
            connection.execute("UPDATE threads SET id = ? WHERE id = ?", (crafted_id, thread.id))
        connection.commit()
    finally:
        connection.close()
    assert (await wr.lookup_record(CHAPEL, "abcdef06")).outcome == LOOKUP_AMBIGUOUS, "premise: the crafted ids are live"

    found = await wr.lookup_record(FORGE, "abcdef06")
    assert (found.outcome, found.complete) == (LOOKUP_FOUND, True)
    assert found.matches[0].candidate.thread_id == crafted[-1]
    hidden = await wr.lookup_record(WORF, "abcdef06")
    absent = await wr.lookup_record(WORF, "abcdef07")
    assert (hidden.outcome, hidden.matches, hidden.complete) == (absent.outcome, absent.matches, absent.complete)
    assert hidden.outcome == LOOKUP_NOT_FOUND and hidden.complete
    await wr.stop()


async def test_a_reached_raw_match_bound_is_reported_incomplete_live_and_archived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lookup_module, "MAX_RAW_MATCHES", 2)
    wr = await _ward_room(tmp_path)
    archive = tmp_path / "ward_room_archive"
    await _attach_archive(wr, archive)
    engineering = await wr.get_channel_by_department("engineering")
    archive.mkdir(parents=True, exist_ok=True)
    (archive / MONTH).write_text(
        "".join(_archive_line(f"abcdef08-0000-4000-8000-00000000000{n}", engineering.id) for n in range(3)),
        encoding="utf-8",
    )
    made = [await wr.create_thread(engineering.id, FORGE, f"Live {n}", "core", author_callsign="Forge") for n in range(2)]
    connection = sqlite3.connect(str(tmp_path / "wr.db"))
    try:
        for n, thread in enumerate(made):
            connection.execute(
                "UPDATE threads SET id = ? WHERE id = ?", (f"abcdef09-0000-4000-8000-00000000000{n}", thread.id),
            )
        connection.commit()
    finally:
        connection.close()

    archived = await wr.lookup_record(FORGE, "abcdef08")
    live = await wr.lookup_record(FORGE, "abcdef09")

    assert (archived.outcome, len(archived.matches), archived.complete) == (LOOKUP_AMBIGUOUS, 2, False)
    assert (live.outcome, len(live.matches), live.complete) == (LOOKUP_AMBIGUOUS, 2, False)
    assert "stopped at a size limit" in render_lookup(live)
    await wr.stop()


async def test_an_ambiguity_lists_four_visible_matches_and_counts_only_the_visible_rest(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    archive = tmp_path / "ward_room_archive"
    await _attach_archive(wr, archive)
    engineering = await wr.get_channel_by_department("engineering")
    medical = await wr.get_channel_by_department("medical")
    archive.mkdir(parents=True, exist_ok=True)
    (archive / MONTH).write_text(
        "".join(_archive_line(f"abcdef0a-0000-4000-8000-00000000000{n}", engineering.id) for n in range(6))
        + _archive_line("abcdef0a-0000-4000-8000-0000000000ff", medical.id),
        encoding="utf-8",
    )

    result = await wr.lookup_record(FORGE, "abcdef0a")

    assert (result.outcome, len(result.matches), result.complete) == (LOOKUP_AMBIGUOUS, 6, True)
    lines = render_lookup(result).splitlines()
    assert len([line for line in lines if line.startswith("- thread ")]) == 4
    assert lines[-1] == "- and 2 more you can see", "the Medical record is not counted"
    await wr.stop()


async def test_a_torn_last_line_makes_every_lookup_incomplete_whatever_it_holds(tmp_path: Path) -> None:
    wr = await _ward_room(tmp_path)
    archive = tmp_path / "ward_room_archive"
    await _attach_archive(wr, archive)
    engineering = await wr.get_channel_by_department("engineering")
    archive.mkdir(parents=True, exist_ok=True)
    first = _archive_line("ff000001-0000-4000-8000-000000000001", engineering.id).encode("utf-8")
    tail = _archive_line("ff000002-0000-4000-8000-000000000002", engineering.id).encode("utf-8")
    month = archive / MONTH
    month.write_bytes(first + tail[:60])  # a prune mid-append: the writer ends every record with a newline

    for ref in ("ff000001", "ff000003"):  # a record before the torn tail, and an id the tail does not hold
        assert (await wr.lookup_record(FORGE, ref)).complete is False, ref
    assert (await wr.lookup_record(FORGE, "ff000001")).outcome == LOOKUP_FOUND

    month.write_bytes(first + tail)  # the writer finished the record
    finished = await wr.lookup_record(FORGE, "ff000002")
    unrelated = await wr.lookup_record(FORGE, "ff000003")
    assert (finished.outcome, finished.complete) == (LOOKUP_FOUND, True)
    assert (unrelated.outcome, unrelated.complete) == (LOOKUP_NOT_FOUND, True)
    await wr.stop()


async def test_the_line_cap_counts_the_newline_and_an_over_cap_line_never_hides_or_eats_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lookup_module, "MAX_LINE_BYTES", 1024)
    wr = await _ward_room(tmp_path)
    archive = tmp_path / "ward_room_archive"
    await _attach_archive(wr, archive)
    engineering = await wr.get_channel_by_department("engineering")
    archive.mkdir(parents=True, exist_ok=True)

    def sized(thread_id: str, size: int) -> bytes:
        """A record of exactly ``size`` bytes, its newline included."""
        bare = _archive_line(thread_id, engineering.id, body="").encode("utf-8")
        return _archive_line(thread_id, engineering.id, body="x" * (size - len(bare))).encode("utf-8")

    month = archive / MONTH
    month.write_bytes(sized("ab000001-0000-4000-8000-000000000001", 1024))
    at_cap = await wr.lookup_record(FORGE, "ab000001")
    assert (at_cap.outcome, at_cap.complete) == (LOOKUP_FOUND, True), "1024 bytes with the newline is within the cap"

    pad = b'{"note": "' + b"p" * 1013 + b'"}'
    assert len(pad) == 1025, "premise: the scanner's first read of the padded line is exactly the cap plus one"
    month.write_bytes(
        sized("ab000002-0000-4000-8000-000000000002", 1025)
        + pad + _archive_line("ab000004-0000-4000-8000-000000000004", engineering.id).encode("utf-8")
        + _archive_line("ab000005-0000-4000-8000-000000000005", engineering.id).encode("utf-8")
    )
    for ref in ("ab000002", "ab000004"):  # over the cap by its newline; a record inside an over-cap line
        result = await wr.lookup_record(FORGE, ref)
        assert (result.outcome, result.complete) == (LOOKUP_NOT_FOUND, False), ref
    after = await wr.lookup_record(FORGE, "ab000005")
    assert (after.outcome, after.complete) == (LOOKUP_FOUND, False), "an over-cap line is skipped, never the line after it"
    await wr.stop()
