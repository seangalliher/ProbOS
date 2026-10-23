# AD-1347 S4: a Ward Room thread or post by id, live or in the prune archive, for the chain's QUERY step

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22

**Status:** build-ready after AD-1347 S1 merges (S1 shares no code file with this slice). Slice 4 of 4 of #1627; it does not close the issue (S2 and S3 remain). **Tier HIGH**: a read path over archived private messages with a privacy rule. **AD number:** AD-1347, from `scripts/ad_ceiling.py` (ceiling AD-1347 from issue titles and prompt filenames, next AD-1348); no new number. **Base:** `origin/main` `3a94845f`. Every code SEARCH anchors on text; the tracker SEARCHes anchor on lines that BF-912 and S1 do not change.

**Tests:** M1 `tests/test_ad1347_s4_ward_room_lookup.py`, 19 functions (27 cases). M2 `tests/test_ad1347_s4_chain_lookup.py`, 9 functions. Updated pins: `tests/test_ad643a_intent_routing.py` (2 asserts), `tests/test_ad645_composition_briefs.py` (2 asserts).

**Line endings:** working copies are CRLF (`core.autocrlf=true`). SEARCH blocks here are LF; match and write with each file's own endings. New files are written LF.

**Not built here:** S2 (the chain's action tags), S3 (execution and report-back), any event-log read in the chain, and tool access in the chain.

**Mechanical repairs by the orchestrator (2026-10-23; no decision changed):** (1) the bridge's capture had turned 23 non-ASCII characters (section signs, em dashes and arrows) into CP437 mojibake; they are restored; (2) section 10's heading said 30 rows while its table holds 32 (L1 to P1); the heading now says 32 and no row changed; (3) so that the phantom precheck is clean, the placeholder spelling of the archive file name in section 0's table row and in the module docstring of section 7.1 is `ward_room_archive_<month>.jsonl`, and the test variable `result` of `test_no_ref_means_no_read_and_a_failing_ward_room_reads_as_unavailable` in section 7.10 is named `handled` (the precheck typed it as the module's result class from other blocks); (4) both new test files stop every service their helpers start in an autouse fixture (`_STARTED`, `_stop_started_services`; the existing `await wr.stop()` calls stay and the second stop is a no-op), because those calls ran only on the passing path: a failed assertion left aiosqlite's non-daemon connection thread alive and the pytest process never exited (found by execution when the first killed mutant, row L1, left `pytest` running past its own summary; Testing Standards, "No test pollution"). No test body, mutation row or acceptance criterion changed, and each file gains one fixture (not a test); (5) the M1 file's case count is 27 (17 plain functions, test 9 with 4 cases and test 11 with 6), as collected from the block, not the 28 the header first said.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| QUERY offers 13 fixed reads chosen by the spec's `context_keys`; the only id-keyed one reads the notified thread from `params` | present | `cognitive/sub_tasks/query.py:419-433`, `:49`; chain specs `cognitive_agent.py:5754`, `:5790` |
| AD-696's one-shot QUERY between triage and execute, fed by an ANALYZE key | present | `cognitive_agent.py:5616-5682`, `:6200-6202`, `:6118` |
| Agents see thread ids as 8-character prefixes | present | `cognitive_agent.py:8338` (`(thread {thread_id[:8]})`) |
| Prune writes one JSON line per thread, with its posts nested, to `ward_room_archive_<month>.jsonl` (named by prune month), then deletes the thread | present | `ward_room/threads.py:908-927`, `:1115-1121`, `:945-959`, `:1019-1020`; `routers/wardroom_admin.py:40-44` |
| AD-485 DM archival only flags `threads.archived = 1`; the row stays, and `get_thread` does not filter it | present | `ward_room/threads.py:814-837`, `:702-706` |
| Visibility is membership (AD-621) | present | `ward_room/channels.py:129-147`; `startup/communication.py:516-537` |
| DM channels subscribe both participants; Captain DM channels are made by `create_channel` and have no membership rows | present | `ward_room/channels.py:263-266`; `proactive.py:4851-4864`; `capability_request_notifier.py:108` |
| The Ward Room stores slot ids; BF-907 resolves sovereign ids; BF-903 recognises visitors | present | `cognitive_agent.py:5838`, `:6088`; `identity.py:157-163`, `:804`; `visiting_officers.py:325-345` |
| `WardRoomService` is about 22 lines under the 500-line SRP trigger, and its baseline row pins `[methods]` | present | `wc -l` 521, class at `service.py:44`; `architecture-baseline.yaml:1010-1017`; `check_architecture_principles.py:187`, `:937-945` |

## 1. Problem

Crew DM'd the Captain for Ward Room reads they cannot make (#1627, live evidence 2026-10-22: a "deleted or voided post", thread `51d91a7d`). In this tree:

- **"Deleted"** is a `posts.deleted` column that no code writes; readers only filter on it (Absence AV2).
- **"Voided"** has no Ward Room meaning (AV3).
- **A post vanishes only when its whole thread is pruned**, after `retention_days` (default 7, `config_models/crew.py:284`), into a monthly JSONL archive that nothing reads back (AV1).
- **The chain cannot look up a thread an agent names.** QUERY's only id-keyed read is keyed by the notification's own thread.

## 2. Solution overview

- **M1, the Ward Room read.** New `ward_room/lookup.py`: `WardRoomRecordLookup` finds candidates by id prefix (live `threads`, then live `posts`, then a bounded archive scan). It keeps the ones the asker may see (AD-621 membership, plus authorship in DM channels) and returns a typed `LookupResult`. `render_lookup` turns that into the chain's text. `WardRoomService` gains `lookup_record` (a thin delegation), and `start_prune_loop` records the archive directory it is given.
- **M2, the chain.**
  - ANALYZE learns `ward_room_lookup` and `ward_room_lookup_ref` (thread and situation prompts).
  - `CognitiveAgent._maybe_dispatch_ward_room_lookup` runs one QUERY step, once per chain and only alongside a communication action.
  - The new operation `ward_room_lookup` calls the service as the chain's `_agent_id`.
  - COMPOSE renders `_ward_room_lookup_context`.

## 3. Decisions

**D1 (route).** ANALYZE names the id; a one-shot QUERY between triage and execute (the AD-696 pattern); gated by a communication action, because a lookup-only triage falls through to the single-call path (`cognitive_agent.py:6329-6336`), which would not render the answer. Who can trigger it: any crew agent on the two chain intents (`_CHAIN_ELIGIBLE_INTENTS`, `cognitive_agent.py:340-343`), through `_build_thread_analysis_prompt` and `_build_situation_review_prompt`. Not the DM comprehension prompt and not the AD-725 DM one-shot path (register R4). Ranked alternatives: a text parse of `thread <hex>` (rejected: it serves ids others name, and git SHAs would trigger scans); a proactive context key (rejected: the agent does not choose it); a loop tool (deferred to AD-1346).

**D2 (one operation).** `ward_room_lookup` resolves a thread id or a post id; the result says which.

**D3 (archive read).** A bounded scan:
- newest file name first, at most `MAX_ARCHIVE_FILES = 12`;
- `MAX_ARCHIVE_BYTES = 64 MiB` read in total;
- `readline(MAX_LINE_BYTES + 1)` with `MAX_LINE_BYTES = 4 MiB`, and an oversized line is read past without being held;
- a byte prefilter on the writer's `json.dumps` shape (`"thread_id": "<ref>`, `"id": "<ref>`), then a parse;
- run in `asyncio.to_thread`.

An oversized, torn or unreadable record, a reached bound, or an unknown archive directory makes the result `complete=False`. The text then says the search stopped, and that note depends on sizes and torn lines, never on visibility. Index at prune time: deferred (a persisted-artifact change and a backfill; not a Captain item). A month convention is impossible.

**D4 (privacy).** For each candidate, `get_channel(channel_id)` must return a channel, else the candidate is not visible. It is visible when the asker is in `get_channel_subscriber_ids(channel_id)`, or when the channel type is `"dm"` and the asker authored the thread or a post in it. Visible matches are counted only after the filter. "Not visible" and "not found" return the same `LookupResult` and the same text. Ward Room visibility has no rank rule, so none is added.

**D5 (identity).** The asker is the chain's `_agent_id` only; a `params` agent id is never the asker. `_requester` returns None for:
- a non-string or blank id;
- a visiting officer (`is_visiting_identity`);
- a sovereign key (`is_sovereign_identity_key`) that `resolve_slot_id` does not map.

A slot id passes unchanged. None means `refused`; there is no fallback, and the key `"captain"` gets no special access.

**D6 (outputs and caps).** Outcomes: `found`, `not_found`, `ambiguous` (two or more visible, listed), `invalid_ref` (not 8 to 36 id characters after strip, lower case and one leading `#`), `refused`, `unavailable`.
- A thread renders its opening post and its last `MAX_POSTS_SHOWN = 12` posts.
- Each body is clipped to `MAX_BODY_CHARS = 400`; the whole text to `MAX_RENDER_CHARS = 2000`.
- An archive-only record is labelled "the Ward Room archive (pruned <UTC>)".
- A post flagged `deleted` shows `[deleted: <reason>]`, never its body.

**D7 (no config).** The feature is on by default and only offers an optional action. Disclosed effect: crew can read the prune archive for their own channels. A flag would add a config field that S1's facade baseline and goldens also pin.

**D8 (placement).** `WardRoomService` gains about 10 lines (it stays under 500). The logic is in `WardRoomRecordLookup`, with five methods, built per call.

**D9 (spine).** No AD-1343 or AD-1346 row is needed: the read calls no stop callee (`tests/fixtures/ad1343_seam_census.py:25`), adds no public `CognitiveAgent` coroutine (`tests/test_ad1343_stop_seam_inventory.py:84-92`; the new method is private), and is no work kind (`admission/taxonomy.py:24-36`). It runs inside an admitted turn.

## 4. Milestones

| Milestone | Opens at | Content | Commit |
|---|---|---|---|
| **M1** | §7.1 | `ward_room/lookup.py`, `WardRoomService.lookup_record` and the archive directory, the M1 tests | one |
| **M2** | §7.4 | the QUERY operation, the two ANALYZE prompts, the COMPOSE section, the dispatch helper and its gate and reset, the two pin updates, the M2 tests | one |
| Trackers | §8 | — | M2's commit or a docs commit |

There are two milestones because M1 is the privacy-bearing seam and is testable on its own; M2 is prompt and chain wiring with different consumers.

## 5. Consumers of every value this changes

| Value | Consumer | Accepts it because |
|---|---|---|
| `WardRoomService.lookup_record` | `_query_ward_room_lookup` (new) | the only caller; exceptions are caught there |
| `WardRoomService._archive_dir` | `lookup_record` only | set by `start_prune_loop`, which `startup/communication.py:540-541` already calls with `data_dir / "ward_room_archive"` |
| `_QUERY_OPERATIONS["ward_room_lookup"]` | `QueryHandler.__call__` (`query.py:505`); `tests/test_ad696_agentic_oracle_retrieval.py:41-42` (membership of another key) | Open/Closed table; no test pins the size or key set (AV4) |
| ANALYZE's `ward_room_lookup` action | `_extract_intended_actions` (lower-cases any string); `find_triggered_skills` (unknown actions match nothing); `_COMM_ACTIONS` (not a member) | additive vocabulary |
| ANALYZE's `ward_room_lookup_ref` | `_maybe_dispatch_ward_room_lookup` only | optional key; JSON parse of the ANALYZE result is unchanged |
| "N keys" text in the two prompts | `test_ad643a_intent_routing.py:520`, `:528`; `test_ad645_composition_briefs.py:66`, `:78` | updated in §7.8 and §7.9 with the reason |
| `observation["_ward_room_lookup_context"]` | `compose._build_user_prompt` (new section) | COMPOSE's context is unfiltered (`sub_task.py:565`) |
| `observation["ward_room_lookup_ref"]`, `["_ward_room_lookup_fired"]` | `_query_ward_room_lookup` (QUERY gets the full context, `sub_task.py:562-569`); the helper's once-per-chain check | reset per routed chain, as AD-696 does |

## 6. Tests

M1 opens at §7.1; M2 opens at §7.4. Real objects throughout: `WardRoomService` over SQLite in `tmp_path`, a real `prune_old_threads` writing the archive, a real `CognitiveAgent`, `SubTaskExecutor` and `QueryHandler`. The stand-ins are:
- `_Identities` (the two identity reads);
- ANALYZE and COMPOSE handlers (no model call; COMPOSE runs the real `_build_user_prompt`);
- `_FailingWardRoom`.

On today's tree every new test fails at import (`probos.ward_room.lookup` and `_query_ward_room_lookup` are absent).

**M1, `tests/test_ad1347_s4_ward_room_lookup.py`**

| # | Test | Acceptance |
|---|---|---|
| 1 | `test_a_member_finds_a_live_thread_by_its_eight_character_prefix` | A1 |
| 2 | `test_a_pruned_thread_is_found_in_the_archive_the_prune_wrote` | A2 (the 51d91a7d case) |
| 3 | `test_the_writer_and_the_scanner_agree_on_the_record_shape` | premise of A2 |
| 4 | `test_a_post_is_found_by_its_own_id_live_and_archived` | A1, A2 |
| 5 | `test_a_department_thread_is_invisible_outside_its_members_and_reads_as_absent` | A3, A4 (the other-department case) |
| 6 | `test_a_dm_thread_is_visible_to_its_participants_only_live_archived_and_after_dm_archival` | A3 (non-participant and participant) |
| 7 | `test_an_author_in_a_captain_dm_channel_with_no_membership_rows_sees_its_own_thread` | A3 |
| 8 | `test_authoring_a_post_does_not_open_a_department_channel` | A3 |
| 9 | `test_an_unidentified_requester_is_refused_before_any_read` (4 cases) | A5 |
| 10 | `test_a_sovereign_id_resolves_to_its_slot_and_an_unresolved_or_visiting_one_is_refused` | A5 |
| 11 | `test_a_ref_that_is_not_8_to_36_id_characters_is_invalid` (6 cases) | A6 |
| 12 | `test_only_visible_records_count_toward_a_match_or_an_ambiguity` | A4, A6 |
| 13 | `test_the_scan_reads_the_newest_twelve_months_and_says_when_it_stopped` | A7 |
| 14 | `test_an_oversized_or_torn_record_is_skipped_and_marks_the_scan_incomplete` | A7 |
| 15 | `test_the_byte_budget_stops_the_scan` | A7 |
| 16 | `test_without_a_known_archive_directory_a_not_found_says_the_search_was_incomplete` | A7 |
| 17 | `test_a_record_in_an_unknown_channel_is_visible_to_no_one` | A3 |
| 18 | `test_a_long_thread_renders_its_last_posts_within_the_character_cap` | A6 |
| 19 | `test_a_post_flagged_deleted_shows_the_flag_and_reason_never_its_body` | A6 |

**M2, `tests/test_ad1347_s4_chain_lookup.py`**

| # | Test | Acceptance |
|---|---|---|
| C1 | `test_the_operation_is_in_the_query_catalog` | A8 |
| C2 | `test_the_asker_is_the_chains_agent_id_never_a_params_agent_id` | A5 |
| C3 | `test_no_ref_means_no_read_and_a_failing_ward_room_reads_as_unavailable` | A8 |
| C4 | `test_the_helper_reads_the_ref_from_analyze_and_runs_once` | A8 |
| C5 | `test_a_lookup_named_in_analyze_reaches_the_compose_prompt_through_the_real_chain` | **A9, the whole seam**: ANALYZE ref → dispatch → executor → handler → operation → service → archive the prune wrote → observation → COMPOSE prompt |
| C6 | `test_a_lookup_with_no_communication_action_reads_nothing` | A9 |
| C7 | `test_each_routed_chain_starts_with_the_lookup_unfired` | A9 |
| C8 | `test_both_analyze_prompts_teach_the_lookup_and_its_key` | A8 |
| C9 | `test_compose_renders_the_record_only_when_one_was_looked_up` | A8 |

**Updated pins (each fails on the M2 tree without its update):**
- `test_ad643a_intent_routing.py::test_situation_review_says_6_keys` ("7 keys" → "8 keys") and `::test_thread_analysis_says_7_keys` ("8 keys" → "9 keys");
- `test_ad645_composition_briefs.py::test_situation_review_prompt_requests_composition_brief` and `::test_thread_analysis_prompt_requests_composition_brief`.

**Hunt (done):**
- No test pins `_QUERY_OPERATIONS`' size or key set (AV4).
- No test bounds the ANALYZE or COMPOSE prompt length (AV5).
- `?raw` readers of `ward_room/service.py` (`test_ad615_wardroom_db_hardening.py:58-78`) check only PRAGMA order and a log string; unaffected.
- `test_ad643a_intent_routing.py:341-354` reads `_execute_chain_with_intent_routing`'s source for substrings that stay.
- `test_ad696_agentic_oracle_retrieval.py:165-209` binds `_maybe_dispatch_oracle_lookup` only.
- The AD-1343 census sees no new stop call or public coroutine.
- The AD-1344 write census counts `open` only with a writing mode (`test_ad1344_constitution_write_refusal.py:827-839`); `lookup.py` opens with the literal `"rb"`.
- `check_store_registry` tracks `CREATE TABLE` modules only (`scripts/check_store_registry.py:15`); `lookup.py` has none.

**Focused commands:**
- M1: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1347_s4_ward_room_lookup.py tests/test_ad1229_message_receipts.py tests/test_ad1229_receipt_facts.py tests/test_ward_room_dms.py tests/test_ad615_wardroom_db_hardening.py -q -n 0 -p no:randomly`, then `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check` (it must show no TRIGGER DRIFT for `WardRoomService`).
- M2: `tests/test_ad1347_s4_chain_lookup.py tests/test_ad696_agentic_oracle_retrieval.py tests/test_ad643a_intent_routing.py tests/test_ad645_composition_briefs.py tests/test_ad462f_memory_refs.py tests/test_ad632a_sub_task_foundation.py tests/test_ad666_sensorium.py tests/test_ad1343_stop_seam_inventory.py`, with the same flags. Drop any file that does not exist.

## 7. The contract

### 7.1 New file: `src/probos/ward_room/lookup.py` (M1)

```python
"""AD-1347 S4 (#1627): one Ward Room thread or post by id, live or in the prune archive.

Crew asked the Captain for reads such as "thread 51d91a7d" or "was that post deleted".
A thread older than ``ward_room.retention_days`` is pruned from the database into the
monthly ``ward_room_archive_<month>.jsonl`` files (AD-416), and nothing read them back.

``WardRoomRecordLookup`` is that read. It finds candidates by id prefix (the live
``threads`` and ``posts`` tables, then a bounded scan of the archive) and keeps only the
ones the asker may see, by AD-621's rule: a member of the record's channel sees it, and
in a DM channel an author of the thread or of a post in it does too (AD-485's Captain
DM channels are created with no membership rows). A record the asker may not see is
reported exactly as one that does not exist. A blank asker, a visiting officer and a
sovereign id that resolves to no slot are refused: no one is assumed.

Bounds: an id of 8 to 36 characters; at most ``MAX_CANDIDATES`` candidates per query;
the newest ``MAX_ARCHIVE_FILES`` files, ``MAX_ARCHIVE_BYTES`` read in all and
``MAX_LINE_BYTES`` per record; ``MAX_RENDER_CHARS`` of text. A scan that stops at a
bound says so. Read-only: it writes nothing and emits no event.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from probos.visiting_officers import is_visiting_identity

logger = logging.getLogger(__name__)

ARCHIVE_GLOB = "ward_room_archive_*.jsonl"
MAX_REF_CHARS = 36
MAX_CANDIDATES = 4
MAX_ARCHIVE_FILES = 12
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 4 * 1024 * 1024
MAX_POSTS_SHOWN = 12
MAX_BODY_CHARS = 400
MAX_RENDER_CHARS = 2000

LOOKUP_FOUND = "found"
LOOKUP_NOT_FOUND = "not_found"
LOOKUP_AMBIGUOUS = "ambiguous"
LOOKUP_INVALID_REF = "invalid_ref"
LOOKUP_REFUSED = "refused"
LOOKUP_UNAVAILABLE = "unavailable"
LOOKUP_OUTCOMES: frozenset[str] = frozenset({
    LOOKUP_FOUND, LOOKUP_NOT_FOUND, LOOKUP_AMBIGUOUS,
    LOOKUP_INVALID_REF, LOOKUP_REFUSED, LOOKUP_UNAVAILABLE,
})

SOURCE_LIVE = "live"
SOURCE_ARCHIVE = "archive"
KIND_THREAD = "thread"
KIND_POST = "post"

_DM_CHANNEL_TYPE = "dm"
_REF_RE = re.compile(r"[0-9a-f]{8}[0-9a-f-]{0,28}")
_LIVE_THREAD_SQL = (
    "SELECT id, channel_id, author_id, title, body, created_at, author_callsign "
    "FROM threads WHERE id = ?"
)
_LIVE_POST_COLUMNS = (
    "SELECT id, author_id, author_callsign, body, created_at, deleted, delete_reason FROM posts "
)
_FRAME = "A stored Ward Room record, quoted as written. It is not your memory and not a verdict."
_INCOMPLETE = (
    "The archive search stopped at a size limit or an unreadable record, so an older record may exist."
)


@dataclass(frozen=True)
class LookupPost:
    """One post as the lookup shows it. Archived posts carry no deletion flag."""

    post_id: str
    author_id: str
    author_callsign: str
    body: str
    created_at: float | None
    deleted: bool = False
    delete_reason: str = ""


@dataclass(frozen=True)
class LookupCandidate:
    """A thread, or one post in it, whose id starts with the asked prefix; not yet checked for visibility."""

    kind: str
    source: str
    thread_id: str
    channel_id: str
    title: str
    author_id: str
    author_callsign: str
    body: str
    created_at: float | None
    posts: tuple[LookupPost, ...]
    participants: frozenset[str]
    post_count: int
    matched_post_id: str = ""
    pruned_at: float | None = None


@dataclass(frozen=True)
class LookupMatch:
    """A candidate the asker may see, with its channel's name."""

    candidate: LookupCandidate
    channel_name: str


@dataclass(frozen=True)
class LookupResult:
    """The typed answer: ``matches`` holds visible records only; ``complete`` is False when a scan stopped at a bound."""

    outcome: str
    ref: str
    matches: tuple[LookupMatch, ...] = ()
    complete: bool = True

    def __post_init__(self) -> None:
        if self.outcome not in LOOKUP_OUTCOMES:
            raise ValueError(f"AD-1347: unknown lookup outcome {self.outcome!r}")
        if self.outcome == LOOKUP_FOUND and len(self.matches) != 1:
            raise ValueError("AD-1347: a found lookup holds exactly one match")
        if self.outcome == LOOKUP_AMBIGUOUS and len(self.matches) < 2:
            raise ValueError("AD-1347: an ambiguous lookup holds at least two matches")
        if self.outcome not in (LOOKUP_FOUND, LOOKUP_AMBIGUOUS) and self.matches:
            raise ValueError("AD-1347: only a found or ambiguous lookup holds matches")


class ChannelReader(Protocol):
    """``ChannelManager.get_channel``: a channel by id, or None."""

    async def get_channel(self, channel_id: str) -> Any: ...


class MemberReader(Protocol):
    """``MessageStore.get_channel_subscriber_ids``: AD-621's members of a channel."""

    async def get_channel_subscriber_ids(self, channel_id: str) -> set[str]: ...


def normalize_ref(ref: object) -> str | None:
    """The id prefix ``ref`` names, in lower case, or None when it is not 8 to 36 id characters."""
    if type(ref) is not str:
        return None
    text = ref.strip().lower().removeprefix("#")
    return text if _REF_RE.fullmatch(text) is not None else None


def _text(value: object) -> str:
    return value if type(value) is str else ""


def _number(value: object) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return float(value)


async def live_candidates(db: Any, ref: str) -> list[LookupCandidate]:
    """Live threads, then live posts, whose id starts with ``ref``: at most ``MAX_CANDIDATES`` of each."""
    async with db.execute(
        "SELECT id FROM threads WHERE substr(id, 1, ?) = ? LIMIT ?", (len(ref), ref, MAX_CANDIDATES),
    ) as cursor:
        thread_ids = [row[0] async for row in cursor]
    async with db.execute(
        "SELECT id, thread_id FROM posts WHERE substr(id, 1, ?) = ? LIMIT ?", (len(ref), ref, MAX_CANDIDATES),
    ) as cursor:
        post_rows = [(row[0], row[1]) async for row in cursor]
    candidates: list[LookupCandidate] = []
    for thread_id in thread_ids:
        candidate = await _live_candidate(db, thread_id, "")
        if candidate is not None:
            candidates.append(candidate)
    for post_id, thread_id in post_rows:
        candidate = await _live_candidate(db, thread_id, post_id)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


async def _live_candidate(db: Any, thread_id: str, matched_post_id: str) -> LookupCandidate | None:
    """The live thread ``thread_id`` with its last posts, or with only ``matched_post_id`` when one is named."""
    async with db.execute(_LIVE_THREAD_SQL, (thread_id,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    async with db.execute("SELECT DISTINCT author_id FROM posts WHERE thread_id = ?", (thread_id,)) as cursor:
        authors = [_text(author[0]) async for author in cursor]
    async with db.execute("SELECT COUNT(*) FROM posts WHERE thread_id = ?", (thread_id,)) as cursor:
        count_row = await cursor.fetchone()
    params: tuple[Any, ...]
    if matched_post_id:
        sql = _LIVE_POST_COLUMNS + "WHERE id = ?"
        params = (matched_post_id,)
    else:
        sql = _LIVE_POST_COLUMNS + "WHERE thread_id = ? ORDER BY created_at DESC LIMIT ?"
        params = (thread_id, MAX_POSTS_SHOWN)
    async with db.execute(sql, params) as cursor:
        posts = [_live_post(post_row) async for post_row in cursor]
    posts.reverse()
    author_id = _text(row[2])
    return LookupCandidate(
        kind=KIND_POST if matched_post_id else KIND_THREAD,
        source=SOURCE_LIVE,
        thread_id=_text(row[0]),
        channel_id=_text(row[1]),
        title=_text(row[3]),
        author_id=author_id,
        author_callsign=_text(row[6]),
        body=_text(row[4]),
        created_at=_number(row[5]),
        posts=tuple(posts),
        participants=frozenset(a for a in (author_id, *authors) if a),
        post_count=int(count_row[0]) if count_row else 0,
        matched_post_id=matched_post_id,
    )


def _live_post(row: Any) -> LookupPost:
    return LookupPost(
        post_id=_text(row[0]),
        author_id=_text(row[1]),
        author_callsign=_text(row[2]),
        body=_text(row[3]),
        created_at=_number(row[4]),
        deleted=bool(row[5]),
        delete_reason=_text(row[6]),
    )


def scan_archive(archive_dir: Any, ref: str) -> tuple[list[LookupCandidate], bool]:
    """Archived threads and posts whose id starts with ``ref``, newest month first. Synchronous; run it off the loop.

    Returns the candidates and whether every archive file was read to its end. A directory
    nothing was pruned into yet is an empty archive. No known directory, an unreadable file,
    an oversized or torn record, or a reached bound makes the scan incomplete. Never raises
    ``OSError``.
    """
    if archive_dir is None:
        return [], False
    root = Path(archive_dir)
    if not root.is_dir():
        return [], True
    try:
        files = sorted((p for p in root.glob(ARCHIVE_GLOB) if p.is_file()), key=lambda p: p.name, reverse=True)
    except OSError:
        logger.warning("AD-1347: the Ward Room archive at %s could not be listed", root, exc_info=True)
        return [], False
    complete = len(files) <= MAX_ARCHIVE_FILES
    thread_marker = b'"thread_id": "' + ref.encode("ascii")
    post_marker = b'"id": "' + ref.encode("ascii")
    budget = MAX_ARCHIVE_BYTES
    found: list[LookupCandidate] = []
    for path in files[:MAX_ARCHIVE_FILES]:
        try:
            with open(path, "rb") as handle:
                while True:
                    if budget <= 0:
                        return found, False
                    line = handle.readline(MAX_LINE_BYTES + 1)
                    if not line:
                        break
                    budget -= len(line)
                    if len(line) > MAX_LINE_BYTES and not line.endswith(b"\n"):
                        complete = False
                        budget = _skip_rest_of_line(handle, budget)
                        continue
                    if thread_marker not in line and post_marker not in line:
                        continue
                    parsed = _archived_candidates(line, ref)
                    if parsed is None:
                        complete = False
                        continue
                    found.extend(parsed)
                    if len(found) >= MAX_CANDIDATES:
                        return found, False
        except OSError:
            logger.warning("AD-1347: the Ward Room archive file %s could not be read", path, exc_info=True)
            complete = False
    return found, complete


def _skip_rest_of_line(handle: BinaryIO, budget: int) -> int:
    """Read past the rest of an oversized record without holding it; returns the budget left."""
    while budget > 0:
        chunk = handle.readline(MAX_LINE_BYTES)
        budget -= len(chunk)
        if not chunk or chunk.endswith(b"\n"):
            break
    return budget


def _archived_candidates(line: bytes, ref: str) -> list[LookupCandidate] | None:
    """The thread and the posts in one archive record that match ``ref``; None for a line that is not a record."""
    try:
        record = json.loads(line)
    except MemoryError:
        raise
    except Exception:  # a torn tail during an append, or a hand edit: not a record, and never fatal
        return None
    if not isinstance(record, dict):
        return None
    thread_id = _text(record.get("thread_id"))
    channel_id = _text(record.get("channel_id"))
    if not thread_id or not channel_id:
        return None
    raw_posts = record.get("posts")
    listed = [_archived_post(p) for p in raw_posts if isinstance(p, dict)] if isinstance(raw_posts, list) else []
    posts = sorted(listed, key=lambda p: p.created_at or 0.0)
    author_id = _text(record.get("author_id"))
    participants = frozenset(a for a in (author_id, *(p.author_id for p in posts)) if a)

    def _candidate(kind: str, shown: tuple[LookupPost, ...], matched_post_id: str = "") -> LookupCandidate:
        return LookupCandidate(
            kind=kind,
            source=SOURCE_ARCHIVE,
            thread_id=thread_id,
            channel_id=channel_id,
            title=_text(record.get("title")),
            author_id=author_id,
            author_callsign=_text(record.get("author_callsign")),
            body=_text(record.get("body")),
            created_at=_number(record.get("created_at")),
            posts=shown,
            participants=participants,
            post_count=len(posts),
            matched_post_id=matched_post_id,
            pruned_at=_number(record.get("pruned_at")),
        )

    matched: list[LookupCandidate] = []
    if thread_id.startswith(ref):
        matched.append(_candidate(KIND_THREAD, tuple(posts[-MAX_POSTS_SHOWN:])))
    for post in posts:
        if post.post_id.startswith(ref):
            matched.append(_candidate(KIND_POST, (post,), post.post_id))
    return matched


def _archived_post(raw: dict) -> LookupPost:
    return LookupPost(
        post_id=_text(raw.get("id")),
        author_id=_text(raw.get("author_id")),
        author_callsign=_text(raw.get("author_callsign")),
        body=_text(raw.get("body")),
        created_at=_number(raw.get("created_at")),
    )


def render_lookup(result: LookupResult) -> str:
    """The chain's text for ``result``: the record, or one line saying why there is none.

    "Not found" reads the same whether the record is absent or not visible to the asker.
    """
    if result.outcome == LOOKUP_FOUND:
        text = "\n".join([_FRAME, *_match_lines(result.matches[0])])
    elif result.outcome == LOOKUP_AMBIGUOUS:
        text = "\n".join([
            f"More than one Ward Room thread or post you can see starts with {result.ref}; "
            "look it up again with more of its id:",
            *(_summary_line(match) for match in result.matches),
        ])
    elif result.outcome == LOOKUP_NOT_FOUND:
        text = f"No Ward Room thread or post with id {result.ref} that you can see is in the Ward Room or its archive."
    elif result.outcome == LOOKUP_INVALID_REF:
        text = f"'{result.ref}' is not a Ward Room id: give 8 to 36 characters of a thread or post id, such as 51d91a7d."
    elif result.outcome == LOOKUP_REFUSED:
        text = "The Ward Room lookup could not confirm who is asking, so it returned nothing."
    else:
        text = "The Ward Room is not available, so the lookup returned nothing."
    if result.complete:
        return text[:MAX_RENDER_CHARS]
    return text[: MAX_RENDER_CHARS - len(_INCOMPLETE) - 1] + "\n" + _INCOMPLETE


def _match_lines(match: LookupMatch) -> list[str]:
    found = match.candidate
    if found.source == SOURCE_LIVE:
        where = "the live Ward Room"
    elif found.pruned_at is not None:
        where = f"the Ward Room archive (pruned {_utc(found.pruned_at)})"
    else:
        where = "the Ward Room archive"
    if found.kind == KIND_POST:
        return [
            f"Post {found.matched_post_id} in thread {found.thread_id}, #{match.channel_name}, from {where}.",
            f"Thread title: {_clip(found.title, MAX_BODY_CHARS)}",
            *(_post_line(post) for post in found.posts),
        ]
    if found.post_count > len(found.posts):
        replies = f"{found.post_count} replies; the last {len(found.posts)}:"
    else:
        replies = f"{found.post_count} replies:"
    return [
        f"Thread {found.thread_id}, #{match.channel_name}, from {where}.",
        f"Title: {_clip(found.title, MAX_BODY_CHARS)}",
        f"Opened by {_who(found.author_callsign, found.author_id)} at {_utc(found.created_at)}: "
        f"{_clip(found.body, MAX_BODY_CHARS)}",
        replies,
        *(_post_line(post) for post in found.posts),
    ]


def _summary_line(match: LookupMatch) -> str:
    found = match.candidate
    record_id = found.matched_post_id or found.thread_id
    return f"- {found.kind} {record_id} in #{match.channel_name}: {_clip(found.title, 80)}"


def _post_line(post: LookupPost) -> str:
    who = _who(post.author_callsign, post.author_id)
    if post.deleted:
        reason = f": {_clip(post.delete_reason, 120)}" if post.delete_reason else ""
        return f"- {who} at {_utc(post.created_at)}: [deleted{reason}]"
    return f"- {who} at {_utc(post.created_at)}: {_clip(post.body, MAX_BODY_CHARS)}"


def _who(callsign: str, author_id: str) -> str:
    return callsign or author_id[:8] or "unknown"


def _clip(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def _utc(value: float | None) -> str:
    if value is None:
        return "an unknown time"
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (OverflowError, OSError, ValueError):
        return "an unknown time"


class WardRoomRecordLookup:
    """AD-1347 S4: the asker's view of one thread or post by id. ``WardRoomService.lookup_record`` builds one per call."""

    def __init__(
        self,
        *,
        db: Any,
        channels: ChannelReader | None,
        members: MemberReader | None,
        identity_registry: Any = None,
    ) -> None:
        self._db = db
        self._channels = channels
        self._members = members
        self._identity_registry = identity_registry

    async def lookup(self, requester_id: object, ref: object, *, archive_dir: Any = None) -> LookupResult:
        """The record ``ref`` names, if ``requester_id`` may see it. A bad input is a typed outcome, never a raise."""
        requester = self._requester(requester_id)
        normalized = normalize_ref(ref)
        if requester is None:
            result = LookupResult(LOOKUP_REFUSED, "")
        elif normalized is None:
            result = LookupResult(LOOKUP_INVALID_REF, _clip(ref if isinstance(ref, str) else "", MAX_REF_CHARS + 4))
        elif self._db is None or self._channels is None or self._members is None:
            result = LookupResult(LOOKUP_UNAVAILABLE, normalized)
        else:
            result = await self._find(requester, normalized, archive_dir)
        logger.info(
            "AD-1347: Ward Room lookup by %s for %r: %s (%d visible)",
            requester or "<refused>", result.ref, result.outcome, len(result.matches),
        )
        return result

    def _requester(self, requester_id: object) -> str | None:
        """The slot a lookup is asked for, or None: blank, a visiting officer, or an unresolved sovereign id."""
        if type(requester_id) is not str or not requester_id.strip():
            return None
        if is_visiting_identity(self._identity_registry, requester_id):
            return None
        from probos.identity import is_sovereign_identity_key  # at use, as visiting_officers imports it

        if not is_sovereign_identity_key(requester_id):
            return requester_id
        if self._identity_registry is None:
            return None
        slot = self._identity_registry.resolve_slot_id(requester_id)
        return slot if type(slot) is str and slot else None

    async def _find(self, requester: str, ref: str, archive_dir: Any) -> LookupResult:
        visible = await self._visible(requester, await live_candidates(self._db, ref))
        complete = True
        if not visible:
            archived, complete = await asyncio.to_thread(scan_archive, archive_dir, ref)
            visible = await self._visible(requester, archived)
        if len(visible) == 1:
            return LookupResult(LOOKUP_FOUND, ref, tuple(visible), complete)
        if visible:
            return LookupResult(LOOKUP_AMBIGUOUS, ref, tuple(visible), complete)
        return LookupResult(LOOKUP_NOT_FOUND, ref, (), complete)

    async def _visible(self, requester: str, candidates: list[LookupCandidate]) -> list[LookupMatch]:
        """AD-621's rule for each candidate; an unknown channel is visible to no one."""
        visible: list[LookupMatch] = []
        for candidate in candidates:
            channel = await self._channels.get_channel(candidate.channel_id)
            if channel is None:
                continue
            members = await self._members.get_channel_subscriber_ids(candidate.channel_id)
            in_dm = channel.channel_type == _DM_CHANNEL_TYPE and requester in candidate.participants
            if requester in members or in_dm:
                visible.append(LookupMatch(candidate=candidate, channel_name=channel.name))
        return visible
```

### 7.2 `src/probos/ward_room/service.py` (M1)

SEARCH:
```python
from probos.ward_room.channels import ChannelManager
from probos.ward_room.messages import MessageStore
from probos.ward_room.models import (
```
REPLACE:
```python
from probos.ward_room.channels import ChannelManager
from probos.ward_room.lookup import LookupResult, WardRoomRecordLookup
from probos.ward_room.messages import MessageStore
from probos.ward_room.models import (
```

SEARCH:
```python
        self._receipt_facts: DmReceiptFacts | None = None  # AD-1229: built in start()
        self._visiting_officers: Any = None  # BF-903: AD-701's registry, attached by finalize when it is on
```
REPLACE:
```python
        self._receipt_facts: DmReceiptFacts | None = None  # AD-1229: built in start()
        self._visiting_officers: Any = None  # BF-903: AD-701's registry, attached by finalize when it is on
        self._archive_dir: Any = None  # AD-1347 S4: where the prune writes its archive; set by start_prune_loop
```

SEARCH:
```python
    async def start_prune_loop(self, config: Any, archive_dir: Any) -> None:
        await self._threads.start_prune_loop(config, archive_dir)

    async def stop_prune_loop(self) -> None:
        await self._threads.stop_prune_loop()
```
REPLACE:
```python
    async def start_prune_loop(self, config: Any, archive_dir: Any) -> None:
        self._archive_dir = archive_dir  # AD-1347 S4: the lookup reads what the prune writes
        await self._threads.start_prune_loop(config, archive_dir)

    async def stop_prune_loop(self) -> None:
        await self._threads.stop_prune_loop()

    async def lookup_record(self, requester_id: str, ref: str) -> LookupResult:
        """AD-1347 S4: one thread or post by id, live or archived, as ``requester_id`` may see it."""
        lookup = WardRoomRecordLookup(
            db=self._db, channels=self._channels, members=self._messages,
            identity_registry=self._identity_registry,
        )
        return await lookup.lookup(requester_id, ref, archive_dir=self._archive_dir)
```

The class body grows by 10 lines, to about 488 of 500. Run `check_architecture_principles.py --check`; if it reports TRIGGER DRIFT for `WardRoomService`, stop and report, and do not update the baseline.

### 7.3 New file: `tests/test_ad1347_s4_ward_room_lookup.py` (M1)

```python
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
    """AD-416's real prune of every thread into one monthly file (a negative retention reaches every thread)."""
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
```

### 7.4 `src/probos/cognitive/sub_tasks/query.py` (M2)

SEARCH:
```python
    except Exception:
        logger.debug("AD-646b: introspective telemetry query failed", exc_info=True)
        return {"introspective_telemetry": ""}
```
REPLACE:
```python
    except Exception:
        logger.debug("AD-646b: introspective telemetry query failed", exc_info=True)
        return {"introspective_telemetry": ""}


async def _query_ward_room_lookup(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """AD-1347 S4 (#1627): one Ward Room thread or post by id, live or archived.

    Reads ``ward_room_lookup_ref`` (ANALYZE names it; ``_maybe_dispatch_ward_room_lookup``
    copies it here) and the asking agent from ``_agent_id`` only: a ``params`` agent id is
    never the asker. The Ward Room decides what the agent may see. Returns
    ``{"ward_room_lookup": <text>}``: empty when no id was asked for, otherwise the record
    or one line saying why there is none. Never raises, so the QUERY step stays a success.
    """
    ref = _ctx(context, "ward_room_lookup_ref")
    if not isinstance(ref, str) or not ref.strip():
        return {"ward_room_lookup": ""}
    from probos.ward_room.lookup import LOOKUP_UNAVAILABLE, LookupResult, render_lookup

    requester = context.get("_agent_id", "")
    ward_room = getattr(runtime, "ward_room", None)
    if ward_room is None:
        return {"ward_room_lookup": render_lookup(LookupResult(LOOKUP_UNAVAILABLE, ""))}
    try:
        result = await ward_room.lookup_record(requester, ref)
    except Exception:
        logger.warning("AD-1347: ward_room_lookup failed for agent %s", requester, exc_info=True)
        result = LookupResult(LOOKUP_UNAVAILABLE, "")
    return {"ward_room_lookup": render_lookup(result)}
```

SEARCH:
```python
    "oracle_lookup": _query_oracle_lookup,                       # AD-696
    "oracle_refs": _query_oracle_refs,                           # AD-462f
}
```
REPLACE:
```python
    "oracle_lookup": _query_oracle_lookup,                       # AD-696
    "oracle_refs": _query_oracle_refs,                           # AD-462f
    "ward_room_lookup": _query_ward_room_lookup,                 # AD-1347 S4
}
```

### 7.5 `src/probos/cognitive/sub_tasks/analyze.py` (M2: both prompts teach the action and its key)

SEARCH:
```python
        f"6. **intended_actions**: Based on your contribution_assessment, what\n"
        f"   specific actions will you take? List as a JSON array from:\n"
        f"   ward_room_reply, endorse, silent, speak_freely, oracle_query.\n"
```
REPLACE:
```python
        f"6. **intended_actions**: Based on your contribution_assessment, what\n"
        f"   specific actions will you take? List as a JSON array from:\n"
        f"   ward_room_reply, endorse, silent, speak_freely, oracle_query,\n"
        f"   ward_room_lookup.\n"
```

SEARCH:
```python
        f"   you would need to look up). Then provide oracle_query_text below.\n"
        f"   Do NOT use oracle_query for general uncertainty — only for\n"
        f"   specific records you would need to retrieve. (AD-696)\n"
        f"   Add \"speak_freely\" if you have something important to communicate\n"
```
REPLACE:
```python
        f"   you would need to look up). Then provide oracle_query_text below.\n"
        f"   Do NOT use oracle_query for general uncertainty — only for\n"
        f"   specific records you would need to retrieve. (AD-696)\n"
        f"   Add \"ward_room_lookup\" ONLY when you need the text of one\n"
        f"   Ward Room thread or post whose id you know (at least its first\n"
        f"   8 characters, as in \"thread 51d91a7d\"), including one pruned\n"
        f"   from the Ward Room. List it with the reply that will use it,\n"
        f"   then provide ward_room_lookup_ref below. (AD-1347)\n"
        f"   Add \"speak_freely\" if you have something important to communicate\n"
```

SEARCH:
```python
        f"8. **oracle_query_text** (optional): If intended_actions contains\n"
        f"   \"oracle_query\", provide the natural-language query string here.\n"
        f"   Be specific (cite names, IDs, dates). Omit or set to null when\n"
        f"   oracle_query is not in intended_actions. (AD-696)\n"
        f"{_format_trigger_awareness(context)}\n"
        f"Return a JSON object with these 8 keys (oracle_query_text optional). No other text."
```
REPLACE:
```python
        f"8. **oracle_query_text** (optional): If intended_actions contains\n"
        f"   \"oracle_query\", provide the natural-language query string here.\n"
        f"   Be specific (cite names, IDs, dates). Omit or set to null when\n"
        f"   oracle_query is not in intended_actions. (AD-696)\n"
        f"9. **ward_room_lookup_ref** (optional): If intended_actions contains\n"
        f"   \"ward_room_lookup\", the thread or post id. Omit or set to null\n"
        f"   when ward_room_lookup is not in intended_actions. (AD-1347)\n"
        f"{_format_trigger_awareness(context)}\n"
        f"Return a JSON object with these 9 keys (oracle_query_text and ward_room_lookup_ref optional). No other text."
```

SEARCH:
```python
        "5. **intended_actions**: What actions will you take? List as a JSON array from:\n"
        "   ward_room_post, ward_room_reply, endorse, notebook, leadership_review,\n"
        "   proposal, dm, silent, speak_freely, oracle_query. Include ALL that apply.\n"
```
REPLACE:
```python
        "5. **intended_actions**: What actions will you take? List as a JSON array from:\n"
        "   ward_room_post, ward_room_reply, endorse, notebook, leadership_review,\n"
        "   proposal, dm, silent, speak_freely, oracle_query, ward_room_lookup.\n"
        "   Include ALL that apply.\n"
```

SEARCH:
```python
        "   or prior decision). Then provide oracle_query_text below. Do NOT\n"
        "   fire oracle_query on general uncertainty — only for specific\n"
        "   records you would need to retrieve. (AD-696)\n"
        "   Add \"speak_freely\" if you have something important to communicate\n"
```
REPLACE:
```python
        "   or prior decision). Then provide oracle_query_text below. Do NOT\n"
        "   fire oracle_query on general uncertainty — only for specific\n"
        "   records you would need to retrieve. (AD-696)\n"
        "   Add \"ward_room_lookup\" ONLY when you need the text of one\n"
        "   Ward Room thread or post whose id you know (at least its first\n"
        "   8 characters, as in \"thread 51d91a7d\"), including one pruned\n"
        "   from the Ward Room. List it with the post, reply or DM that will\n"
        "   use it, then provide ward_room_lookup_ref below. (AD-1347)\n"
        "   Add \"speak_freely\" if you have something important to communicate\n"
```

SEARCH:
```python
        "7. **oracle_query_text** (optional): If intended_actions contains\n"
        "   \"oracle_query\", provide the natural-language query string here.\n"
        "   Be specific (cite names, IDs, dates). Omit or set to null when\n"
        "   oracle_query is not in intended_actions. (AD-696)\n"
        f"{_format_trigger_awareness(context)}\n"
        "Return a JSON object with these 7 keys (oracle_query_text optional). No other text."
```
REPLACE:
```python
        "7. **oracle_query_text** (optional): If intended_actions contains\n"
        "   \"oracle_query\", provide the natural-language query string here.\n"
        "   Be specific (cite names, IDs, dates). Omit or set to null when\n"
        "   oracle_query is not in intended_actions. (AD-696)\n"
        "8. **ward_room_lookup_ref** (optional): If intended_actions contains\n"
        "   \"ward_room_lookup\", the thread or post id. Omit or set to null\n"
        "   when ward_room_lookup is not in intended_actions. (AD-1347)\n"
        f"{_format_trigger_awareness(context)}\n"
        "Return a JSON object with these 8 keys (oracle_query_text and ward_room_lookup_ref optional). No other text."
```

### 7.6 `src/probos/cognitive/sub_tasks/compose.py` (M2)

SEARCH:
```python
            "These are NOT your personal experiences. They are from the ship's shared "
            "knowledge stores. Treat as reference material, not memory.\n\n"
            + _oracle
        )
```
REPLACE:
```python
            "These are NOT your personal experiences. They are from the ship's shared "
            "knowledge stores. Treat as reference material, not memory.\n\n"
            + _oracle
        )

    # AD-1347 S4: a Ward Room thread or post the agent looked up by id (live or archived)
    _wr_lookup = context.get("_ward_room_lookup_context", "")
    if _wr_lookup:
        parts.append(
            "## Ward Room Record (looked up by id)\n\n"
            "You asked for this record by its id. It is quoted as stored; cite it as "
            "the Ward Room's record, not as your memory.\n\n"
            + _wr_lookup
        )
```

### 7.7 `src/probos/cognitive/cognitive_agent.py` (M2: the helper, its gate and its per-chain reset)

SEARCH:
```python
                if formatted:
                    observation["_oracle_context"] = formatted
                break

    @staticmethod
    def _extract_intended_actions(chain_results: list) -> list[str]:
```
REPLACE:
```python
                if formatted:
                    observation["_oracle_context"] = formatted
                break

    async def _maybe_dispatch_ward_room_lookup(
        self, triage_results: list, observation: dict,
    ) -> None:
        """AD-1347 S4: look up one Ward Room thread or post by id, between triage and execute.

        Reads ``ward_room_lookup_ref`` from the latest successful ANALYZE result, runs a
        one-step QUERY chain (``ward_room_lookup``) and writes the text to
        ``observation["_ward_room_lookup_context"]``, which COMPOSE renders. Once per chain.
        The Ward Room decides what this agent may see; this only carries the id.
        """
        if observation.get("_ward_room_lookup_fired"):
            return
        from probos.cognitive.sub_task import SubTaskChain, SubTaskSpec, SubTaskType

        ref = ""
        for r in reversed(triage_results):
            if r.sub_task_type == SubTaskType.ANALYZE and r.success and r.result:
                raw_ref = r.result.get("ward_room_lookup_ref")
                ref = raw_ref.strip() if isinstance(raw_ref, str) else ""
                break
        if not ref:
            return
        observation["ward_room_lookup_ref"] = ref
        observation["_ward_room_lookup_fired"] = True
        if self._sub_task_executor is None:
            return
        lookup_chain = SubTaskChain(
            steps=[
                SubTaskSpec(
                    sub_task_type=SubTaskType.QUERY,
                    name="ward-room-lookup",
                    context_keys=("ward_room_lookup",),
                ),
            ],
            chain_timeout_ms=30000,
            fallback="skip",
            source="ad1347:ward_room_lookup",
        )
        try:
            results = await self._sub_task_executor.execute(
                lookup_chain,
                observation,
                agent_id=self.id,
                agent_type=self.agent_type,
                intent=observation.get("intent", ""),
                intent_id=observation.get("intent_id", ""),
                journal=self._cognitive_journal,
            )
        except Exception:
            logger.warning("AD-1347: ward_room_lookup chain failed for %s", self.agent_type, exc_info=True)
            return
        for r in results:
            if r.sub_task_type == SubTaskType.QUERY and r.success and r.result:
                text = r.result.get("ward_room_lookup", "")
                if isinstance(text, str) and text:
                    observation["_ward_room_lookup_context"] = text
                break

    @staticmethod
    def _extract_intended_actions(chain_results: list) -> list[str]:
```

SEARCH:
```python
        except Exception:
            observation["_recall_tier"] = None  # Gate-closed by default
        observation["_oracle_lookup_fired"] = False  # AD-696 (DLog #4)
```
REPLACE:
```python
        except Exception:
            observation["_recall_tier"] = None  # Gate-closed by default
        observation["_oracle_lookup_fired"] = False  # AD-696 (DLog #4)
        observation["_ward_room_lookup_fired"] = False  # AD-1347 S4 (once per chain)
```

SEARCH:
```python
        _COMM_ACTIONS = frozenset({"ward_room_post", "ward_room_reply", "endorse", "dm"})
        has_comm_action = bool(_COMM_ACTIONS.intersection(intended_actions))
```
REPLACE:
```python
        _COMM_ACTIONS = frozenset({"ward_room_post", "ward_room_reply", "endorse", "dm"})
        has_comm_action = bool(_COMM_ACTIONS.intersection(intended_actions))

        # AD-1347 S4: a Ward Room record by id, only when an action will use it; a
        # non-communication triage falls through to the single call, which would not render it.
        if has_comm_action and "ward_room_lookup" in intended_actions:
            await self._maybe_dispatch_ward_room_lookup(triage_results, observation)
```

### 7.8 `tests/test_ad643a_intent_routing.py` (M2: the pinned key counts)

SEARCH:
```python
    def test_situation_review_says_6_keys(self):
        """Situation review prompt says '7 keys' (AD-696 added oracle_query_text optional)."""
        from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt
        _, user = _build_situation_review_prompt(
            {"context": "test"}, [], "TestAgent", "Science",
        )
        assert "7 keys" in user

    def test_thread_analysis_says_7_keys(self):
        """Thread analysis prompt says '8 keys' (AD-696 added oracle_query_text optional)."""
        from probos.cognitive.sub_tasks.analyze import _build_thread_analysis_prompt
        _, user = _build_thread_analysis_prompt(
            {"context": "test", "params": {}}, [], "TestAgent", "Science",
        )
        assert "8 keys" in user
```
REPLACE:
```python
    def test_situation_review_says_6_keys(self):
        """Situation review prompt says '8 keys' (AD-696 oracle_query_text; AD-1347 S4 ward_room_lookup_ref, both optional)."""
        from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt
        _, user = _build_situation_review_prompt(
            {"context": "test"}, [], "TestAgent", "Science",
        )
        assert "8 keys" in user  # AD-1347 S4: was 7; the optional ward_room_lookup_ref joined

    def test_thread_analysis_says_7_keys(self):
        """Thread analysis prompt says '9 keys' (AD-696 oracle_query_text; AD-1347 S4 ward_room_lookup_ref, both optional)."""
        from probos.cognitive.sub_tasks.analyze import _build_thread_analysis_prompt
        _, user = _build_thread_analysis_prompt(
            {"context": "test", "params": {}}, [], "TestAgent", "Science",
        )
        assert "9 keys" in user  # AD-1347 S4: was 8; the optional ward_room_lookup_ref joined
```

### 7.9 `tests/test_ad645_composition_briefs.py` (M2: the pinned key counts)

SEARCH:
```python
        assert "sources_to_draw_on" in user
        assert "7 keys" in user

    def test_thread_analysis_prompt_requests_composition_brief(self):
```
REPLACE:
```python
        assert "sources_to_draw_on" in user
        assert "8 keys" in user  # AD-1347 S4: was 7; the optional ward_room_lookup_ref joined

    def test_thread_analysis_prompt_requests_composition_brief(self):
```

SEARCH:
```python
        assert "sources_to_draw_on" in user
        assert "8 keys" in user

    def test_dm_comprehension_prompt_requests_composition_brief(self):
```
REPLACE:
```python
        assert "sources_to_draw_on" in user
        assert "9 keys" in user  # AD-1347 S4: was 8; the optional ward_room_lookup_ref joined

    def test_dm_comprehension_prompt_requests_composition_brief(self):
```

### 7.10 New file: `tests/test_ad1347_s4_chain_lookup.py` (M2)

```python
"""AD-1347 S4 (#1627) M2: the chain asks for a Ward Room record by id, and COMPOSE sees the answer.

Real ``CognitiveAgent``, ``SubTaskExecutor``, ``QueryHandler`` and ``WardRoomService`` (an archive
the real prune wrote in ``tmp_path``). ANALYZE and COMPOSE are stand-ins with no model call:
ANALYZE returns its JSON contract, and COMPOSE records the prompt the real
``_build_user_prompt`` makes from the context it is given.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.sub_task import SubTaskExecutor, SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt, _build_thread_analysis_prompt
from probos.cognitive.sub_tasks.compose import _build_user_prompt
from probos.cognitive.sub_tasks.query import _QUERY_OPERATIONS, QueryHandler, _query_ward_room_lookup
from probos.config_models.crew import WardRoomConfig
from probos.ward_room.service import WardRoomService

FORGE = "forge-1"
LAFORGE = "laforge-1"
CHAPEL = "chapel-1"
ARCHIVED_BODY = "Loop B read 41 C at 0300."
UNAVAILABLE = "The Ward Room is not available, so the lookup returned nothing."
_SPEC = SubTaskSpec(sub_task_type=SubTaskType.QUERY, name="lookup", context_keys=("ward_room_lookup",))


class _Runtime:
    """The one runtime attribute ``QueryHandler`` reads for this operation."""

    def __init__(self, ward_room: Any) -> None:
        self.ward_room = ward_room


class _FailingWardRoom:
    async def lookup_record(self, requester_id: str, ref: str) -> Any:
        raise sqlite3.OperationalError("database is locked")


class _Analysis:
    """ANALYZE's JSON contract (``intended_actions`` and the new ref), with no model call."""

    def __init__(self, result: dict) -> None:
        self._result = result

    async def __call__(self, spec: Any, context: dict, prior_results: list) -> SubTaskResult:
        return SubTaskResult(sub_task_type=SubTaskType.ANALYZE, name=spec.name, result=dict(self._result), success=True)


class _Compose:
    """Records the COMPOSE user prompt the real builder makes from the context it is given."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def __call__(self, spec: Any, context: dict, prior_results: list) -> SubTaskResult:
        self.prompts.append(_build_user_prompt(context, prior_results))
        return SubTaskResult(sub_task_type=SubTaskType.COMPOSE, name=spec.name, result={"output": "Acknowledged."}, success=True)


_STARTED: list[Any] = []


@pytest.fixture(autouse=True)
async def _stop_started_services() -> AsyncIterator[None]:
    """A failed assertion skips the test's own ``stop()``, and an open connection keeps the interpreter from exiting."""
    yield
    while _STARTED:
        await _STARTED.pop().stop()


async def _ship(tmp_path: Path) -> tuple[Any, str, str]:
    """A started Ward Room: an Engineering thread pruned into the archive, and a live one to reply in."""
    started = WardRoomService(db_path=str(tmp_path / "wr.db"))
    await started.start()
    _STARTED.append(started)
    engineering = await started.get_channel_by_department("engineering")
    for agent_id in (FORGE, LAFORGE):
        await started.subscribe(agent_id, engineering.id)
    archive = tmp_path / "ward_room_archive"
    await started.start_prune_loop(WardRoomConfig(prune_interval_seconds=3600.0), archive)
    await started.stop_prune_loop()
    pruned = await started.create_thread(engineering.id, LAFORGE, "Coolant audit", ARCHIVED_BODY, author_callsign="LaForge")
    await started.prune_old_threads(
        retention_days=-1, retention_days_endorsed=-1, archive_path=str(archive / "ward_room_archive_2026-10.jsonl"),
    )
    live = await started.create_thread(
        engineering.id, LAFORGE, "Follow-up", "Forge, what did the coolant audit say?", author_callsign="LaForge",
    )
    return started, pruned.id, live.id


def _executor(wr: Any, analysis: dict, compose: _Compose) -> SubTaskExecutor:
    executor = SubTaskExecutor(config=None)
    executor.register_handler(SubTaskType.QUERY, QueryHandler(_Runtime(wr)))
    executor.register_handler(SubTaskType.ANALYZE, _Analysis(analysis))
    executor.register_handler(SubTaskType.COMPOSE, compose)
    return executor


def _agent(executor: Any) -> Any:
    """A real agent; returned as ``Any`` so the precheck does not type it before the new method exists."""
    built = CognitiveAgent(agent_id=FORGE, instructions="Test instructions.", runtime=None)
    built.agent_type = "engineering_officer"
    built.callsign = "Forge"
    built.set_sub_task_executor(executor)
    return built


def _observation(live_id: str) -> dict:
    return {
        "intent": "ward_room_notification",
        "intent_id": "ad1347-s4",
        "context": "LaForge: Forge, what did the coolant audit say?",
        "params": {
            "thread_id": live_id, "channel_name": "Engineering", "is_dm_channel": False,
            "author_id": LAFORGE, "author_callsign": "LaForge",
            "title": "Follow-up", "text": "Forge, what did the coolant audit say?",
        },
    }


def test_the_operation_is_in_the_query_catalog() -> None:
    assert _QUERY_OPERATIONS["ward_room_lookup"] is _query_ward_room_lookup


async def test_the_asker_is_the_chains_agent_id_never_a_params_agent_id(tmp_path: Path) -> None:
    wr, pruned_id, _ = await _ship(tmp_path)
    ref = pruned_id[:8]

    smuggled = await _query_ward_room_lookup(_Runtime(wr), _SPEC, {"ward_room_lookup_ref": ref, "params": {"agent_id": FORGE}})
    own = await _query_ward_room_lookup(_Runtime(wr), _SPEC, {"ward_room_lookup_ref": ref, "_agent_id": FORGE})
    outsider = await _query_ward_room_lookup(_Runtime(wr), _SPEC, {"ward_room_lookup_ref": ref, "_agent_id": CHAPEL})

    assert smuggled == {"ward_room_lookup": "The Ward Room lookup could not confirm who is asking, so it returned nothing."}
    assert ARCHIVED_BODY in own["ward_room_lookup"]
    assert outsider["ward_room_lookup"].startswith("No Ward Room thread or post with id ")
    await wr.stop()


async def test_no_ref_means_no_read_and_a_failing_ward_room_reads_as_unavailable() -> None:
    assert await _query_ward_room_lookup(_Runtime(None), _SPEC, {"_agent_id": FORGE}) == {"ward_room_lookup": ""}
    assert await _query_ward_room_lookup(
        _Runtime(None), _SPEC, {"_agent_id": FORGE, "ward_room_lookup_ref": "   "},
    ) == {"ward_room_lookup": ""}
    assert await _query_ward_room_lookup(
        _Runtime(None), _SPEC, {"_agent_id": FORGE, "ward_room_lookup_ref": "aa000001"},
    ) == {"ward_room_lookup": UNAVAILABLE}

    handled = await QueryHandler(_Runtime(_FailingWardRoom()))(
        _SPEC, {"_agent_id": FORGE, "ward_room_lookup_ref": "aa000001"}, [],
    )
    assert handled.success and handled.result == {"ward_room_lookup": UNAVAILABLE}


async def test_the_helper_reads_the_ref_from_analyze_and_runs_once(tmp_path: Path) -> None:
    wr, pruned_id, _ = await _ship(tmp_path)
    agent = _agent(_executor(wr, {}, _Compose()))
    triage = [SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE, name="analyze-thread", success=True,
        result={"intended_actions": ["ward_room_reply", "ward_room_lookup"], "ward_room_lookup_ref": f" {pruned_id[:8]} "},
    )]
    observation: dict = {"_agent_id": FORGE, "intent": "ward_room_notification"}

    await agent._maybe_dispatch_ward_room_lookup(triage, observation)

    assert observation["ward_room_lookup_ref"] == pruned_id[:8]
    assert observation["_ward_room_lookup_fired"] is True
    assert ARCHIVED_BODY in observation["_ward_room_lookup_context"]

    again: dict = {"_agent_id": FORGE, "_ward_room_lookup_fired": True}
    await agent._maybe_dispatch_ward_room_lookup(triage, again)
    assert "_ward_room_lookup_context" not in again

    for bad in (None, "", "   ", 5):
        blank = [SubTaskResult(sub_task_type=SubTaskType.ANALYZE, name="a", success=True, result={"ward_room_lookup_ref": bad})]
        untouched: dict = {"_agent_id": FORGE}
        await agent._maybe_dispatch_ward_room_lookup(blank, untouched)
        assert untouched == {"_agent_id": FORGE}, bad
    await wr.stop()


async def test_a_lookup_named_in_analyze_reaches_the_compose_prompt_through_the_real_chain(tmp_path: Path) -> None:
    wr, pruned_id, live_id = await _ship(tmp_path)
    compose = _Compose()
    analysis = {
        "intended_actions": ["ward_room_reply", "ward_room_lookup"],
        "ward_room_lookup_ref": pruned_id[:8],
        "contribution_assessment": "RESPOND",
    }
    agent = _agent(_executor(wr, analysis, compose))
    observation = _observation(live_id)

    await agent._execute_chain_with_intent_routing(observation)

    assert compose.prompts, "premise: the communication chain ran to COMPOSE"
    prompt = compose.prompts[-1]
    assert "## Ward Room Record (looked up by id)" in prompt
    assert ARCHIVED_BODY in prompt
    assert "the Ward Room archive (pruned " in prompt
    await wr.stop()


async def test_a_lookup_with_no_communication_action_reads_nothing(tmp_path: Path) -> None:
    wr, pruned_id, live_id = await _ship(tmp_path)
    compose = _Compose()
    analysis = {"intended_actions": ["notebook", "ward_room_lookup"], "ward_room_lookup_ref": pruned_id[:8]}
    agent = _agent(_executor(wr, analysis, compose))
    observation = _observation(live_id)

    assert await agent._execute_chain_with_intent_routing(observation) is None

    assert "_ward_room_lookup_context" not in observation
    assert observation["_ward_room_lookup_fired"] is False
    assert compose.prompts == []
    await wr.stop()


async def test_each_routed_chain_starts_with_the_lookup_unfired(tmp_path: Path) -> None:
    wr, pruned_id, live_id = await _ship(tmp_path)
    analysis = {"intended_actions": ["ward_room_reply", "ward_room_lookup"], "ward_room_lookup_ref": pruned_id[:8]}
    agent = _agent(_executor(wr, analysis, _Compose()))
    observation = _observation(live_id)
    observation["_ward_room_lookup_fired"] = True  # left over from an earlier chain on a reused dict

    await agent._execute_chain_with_intent_routing(observation)

    assert ARCHIVED_BODY in observation["_ward_room_lookup_context"]
    await wr.stop()


def test_both_analyze_prompts_teach_the_lookup_and_its_key() -> None:
    _, thread_user = _build_thread_analysis_prompt({"context": "test", "params": {}}, [], "Forge", "Engineering")
    _, situation_user = _build_situation_review_prompt({"context": "test"}, [], "Forge", "Engineering")

    for user in (thread_user, situation_user):
        assert '"ward_room_lookup"' in user and "ward_room_lookup_ref" in user
    assert "9 keys" in thread_user and "8 keys" in situation_user


def test_compose_renders_the_record_only_when_one_was_looked_up() -> None:
    with_record = _build_user_prompt({"_ward_room_lookup_context": "RECORD TEXT"}, [])

    assert "## Ward Room Record (looked up by id)" in with_record and "RECORD TEXT" in with_record
    assert "Ward Room Record" not in _build_user_prompt({}, [])
```

If `_execute_chain_with_intent_routing` raises in its preamble with `runtime=None`, give `CognitiveAgent` the `_Runtime(wr)` instance instead. If it then reads more attributes, add each to `_Runtime` as a plain `None` field. Do not mock, and record what was added in the build report.

## 8. Tracking (tracker pairs; in M2's commit, or a docs-only commit after it)

Set the date to the commit date. The anchors survive BF-912's and S1's entries:
- **PROGRESS:** both insert directly below the title, and this pair anchors on the title and the blank line only. The S4 entry lands above theirs (newest first).
- **DECISIONS:** both insert before the "Explicit delegation models" heading, and this pair anchors on that heading alone. S4's entry follows theirs.

**`PROGRESS.md`** (title plus the blank line; occurs once):

SEARCH:
```markdown
# ProbOS Progress

```
REPLACE:
```markdown
# ProbOS Progress

**AD-1347 S4 (2026-10-23), #1627 slice 4 of 4 -- a crew agent can look up one Ward Room thread or post by id, including one pruned into the Ward Room archive, from its own chain.** ANALYZE (thread and situation prompts) learns the action `ward_room_lookup` and the optional key `ward_room_lookup_ref`; `CognitiveAgent._maybe_dispatch_ward_room_lookup` runs one QUERY step between triage and execute, once per chain and only alongside a communication action; the new QUERY operation `ward_room_lookup` asks `WardRoomService.lookup_record` as the chain's `_agent_id`, and COMPOSE renders the answer. New `probos/ward_room/lookup.py` (`WardRoomRecordLookup`, `LookupResult`, `render_lookup`): live threads and posts by an 8-36 character id prefix, then a bounded scan of `ward_room_archive_*.jsonl` (newest 12 files, 64 MiB, 4 MiB a record; an incomplete scan says so). Visibility is AD-621's membership, plus authorship in DM channels (AD-485's Captain DM channels have no members); a record the asker may not see reads exactly as one that does not exist; a blank asker, a visiting officer or an unresolved sovereign id is refused. `start_prune_loop` records the archive directory. No config, no schema, no census row. New: `tests/test_ad1347_s4_ward_room_lookup.py`, `tests/test_ad1347_s4_chain_lookup.py`. Updated pins: `test_ad643a_intent_routing.py`, `test_ad645_composition_briefs.py` (the key counts). The contract is `prompts/ad-1347-s4-archive-aware-thread-and-post-lookup.md`.

```

**`DECISIONS.md`** (anchored on the next heading; occurs once):

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### AD-1347 S4 -- A Ward Room thread or post by id, live or in the prune archive, for the chain's QUERY step (2026-10-23, #1627 slice 4 of 4)

- *Scope.* Slice 4 of #1627, two milestone commits. Files: new `ward_room/lookup.py`; `ward_room/service.py` (`lookup_record`, the archive directory); `cognitive/sub_tasks/query.py`, `analyze.py`, `compose.py`; `cognitive/cognitive_agent.py`; tests. Contract: `prompts/ad-1347-s4-archive-aware-thread-and-post-lookup.md`.
- *D1 (route).* ANALYZE names the id (AD-696's one-shot QUERY shape), gated by a communication action so the answer is never discarded; rejected a text parse (git SHAs share the shape) and a proactive context key; a loop tool waits for AD-1346.
- *D2 (archive).* A bounded scan, newest month first, with a byte prefilter on the writer's JSON shape; a prune-time index deferred until live sizes call for it.
- *D3 (privacy).* AD-621 membership reused; authorship counts only in DM channels; an unknown channel is visible to no one; invisible reads as absent; the asker is `_agent_id` only, resolved through BF-907, visitors refused.
- *D4 (no flag).* Nothing becomes readable that a member could not read; retention for one's own channels is what changes.
- *Disclosed effects.* Every chain agent's two ANALYZE prompts gain one optional action and key. The prune archive is now read, by participants and members only.
- *Reversal.* Revert the two commits; the archive and the database are unchanged.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` to regenerate `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`, and commit them with the trackers. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`, never by comparing bytes. If S1's regenerated files are already on the base, regenerate again; do not hand-merge them.

**`docs/development/roadmap.md`:** no row; AD-1347 does not appear there (AV6).

## 9. What this does NOT change

- `ThreadManager.prune_old_threads`, `archive_dm_messages`, the archive's format and location, and retention.
- The membership rule and every existing Ward Room read; `get_thread` and the 13 existing QUERY operations.
- `_build_dm_comprehension_prompt`, the AD-725 DM one-shot lookup, and the single-call prompts' oracle sections.
- Any config model, the config-facade baseline, the profiles manifest, the architecture baseline and the store registry.
- The AD-1343 seam registry and census, and the AD-1346 taxonomy.
- S1's `agent_work` service (not called), S2's tags and S3's execution.
- Tools and the tool registry: no new tool; `event_log_query` stays loop-only.
- AD-1119's resolvers (register R1).

## 10. Mutation rows (32 rows; whole stripped lines, each occurring once in its file after §7)

Tier HIGH. Run each row against the named test on the contract-applied tree, after an unmutated baseline run that passes, and restore each file before the next row. None of these has been executed; the build's campaign is the campaign of record.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| L1 | `src/probos/ward_room/lookup.py` | `if requester is None:` | `if False:` | test 9 (a blank asker reads as not_found, not refused) |
| L2 | `src/probos/ward_room/lookup.py` | `if type(requester_id) is not str or not requester_id.strip():` | `if type(requester_id) is not str:` | test 9 (the whitespace case) |
| L3 | `src/probos/ward_room/lookup.py` | `if is_visiting_identity(self._identity_registry, requester_id):` | `if False:` | test 10 (the visitor's mapped slot is found) |
| L4 | `src/probos/ward_room/lookup.py` | `if not is_sovereign_identity_key(requester_id):` | `if True:` | test 10 (the resolved id is no longer found; the unresolved one is not refused) |
| L5 | `src/probos/ward_room/lookup.py` | `return slot if type(slot) is str and slot else None` | `return requester_id` | test 10 (the unresolved id is not refused) |
| L6 | `src/probos/ward_room/lookup.py` | `in_dm = channel.channel_type == _DM_CHANNEL_TYPE and requester in candidate.participants` | `in_dm = requester in candidate.participants` | test 8 |
| L7 | `src/probos/ward_room/lookup.py` | `in_dm = channel.channel_type == _DM_CHANNEL_TYPE and requester in candidate.participants` | `in_dm = False` | test 7 |
| L8 | `src/probos/ward_room/lookup.py` | `if requester in members or in_dm:` | `if True:` | tests 5 and 6 |
| L9 | `src/probos/ward_room/lookup.py` | `if channel is None:` | `if False:` | test 17 (raises on a None channel) |
| L10 | `src/probos/ward_room/lookup.py` | `if not visible:` | `if False:` | test 2 |
| L11 | `src/probos/ward_room/lookup.py` | `if len(visible) == 1:` | `if len(visible) >= 1:` | test 12 (a found result with two matches raises) |
| L12 | `src/probos/ward_room/lookup.py` | `files = sorted((p for p in root.glob(ARCHIVE_GLOB) if p.is_file()), key=lambda p: p.name, reverse=True)` | `files = sorted((p for p in root.glob(ARCHIVE_GLOB) if p.is_file()), key=lambda p: p.name, reverse=False)` | test 13 (the newest month is not read) |
| L13 | `src/probos/ward_room/lookup.py` | `for path in files[:MAX_ARCHIVE_FILES]:` | `for path in files:` | test 13 (the thirteenth month is found) |
| L14 | `src/probos/ward_room/lookup.py` | `complete = len(files) <= MAX_ARCHIVE_FILES` | `complete = True` | test 13 |
| L15 | `src/probos/ward_room/lookup.py` | `if len(line) > MAX_LINE_BYTES and not line.endswith(b"\n"):` | `if False:` | test 14 (`after.complete` becomes True) |
| L16 | `src/probos/ward_room/lookup.py` | `if thread_marker not in line and post_marker not in line:` | `if thread_marker not in line:` | test 4 (the archived post) |
| L17 | `src/probos/ward_room/lookup.py` | `if budget <= 0:` | `if False:` | test 15 |
| L18 | `src/probos/ward_room/lookup.py` | `if thread_id.startswith(ref):` | `if True:` | test 4 (the archived post becomes ambiguous) |
| L19 | `src/probos/ward_room/lookup.py` | `if post.post_id.startswith(ref):` | `if True:` | test 2 (the archived thread becomes ambiguous) |
| L20 | `src/probos/ward_room/lookup.py` | `text = ref.strip().lower().removeprefix("#")` | `text = ref` | test 1 (the `#` upper-case form) |
| L21 | `src/probos/ward_room/lookup.py` | `_REF_RE = re.compile(r"[0-9a-f]{8}[0-9a-f-]{0,28}")` | `_REF_RE = re.compile(r"[0-9a-f]{7}[0-9a-f-]{0,29}")` | test 11 (the 7-character case) |
| L22 | `src/probos/ward_room/lookup.py` | `"SELECT id FROM threads WHERE substr(id, 1, ?) = ? LIMIT ?", (len(ref), ref, MAX_CANDIDATES),` | `"SELECT id FROM threads WHERE id = ? AND length(?) > 0 LIMIT ?", (ref, ref, MAX_CANDIDATES),` | test 1 (the 8-character prefix) |
| L23 | `src/probos/ward_room/lookup.py` | `if post.deleted:` | `if False:` | test 19 |
| L24 | `src/probos/ward_room/lookup.py` | `return text[:MAX_RENDER_CHARS]` | `return text` | test 18 |
| S1 | `src/probos/ward_room/service.py` | `self._archive_dir = archive_dir  # AD-1347 S4: the lookup reads what the prune writes` | `pass` | tests 2 and 16 |
| S2 | `src/probos/ward_room/service.py` | `return await lookup.lookup(requester_id, ref, archive_dir=self._archive_dir)` | `return await lookup.lookup(requester_id, ref, archive_dir=None)` | test 2 |
| Q1 | `src/probos/cognitive/sub_tasks/query.py` | `requester = context.get("_agent_id", "")` | `requester = context.get("_agent_id", "") or _ctx(context, "agent_id")` | C2 |
| Q2 | `src/probos/cognitive/sub_tasks/query.py` | `"ward_room_lookup": _query_ward_room_lookup,                 # AD-1347 S4` | `"ward_room_lookup_off": _query_ward_room_lookup,             # AD-1347 S4` | C1, C5 |
| G1 | `src/probos/cognitive/cognitive_agent.py` | `if has_comm_action and "ward_room_lookup" in intended_actions:` | `if "ward_room_lookup" in intended_actions:` | C6 |
| G2 | `src/probos/cognitive/cognitive_agent.py` | `observation["_ward_room_lookup_fired"] = False  # AD-1347 S4 (once per chain)` | `pass` | C7 |
| G3 | `src/probos/cognitive/cognitive_agent.py` | `observation["_ward_room_lookup_context"] = text` | `pass` | C4, C5 |
| P1 | `src/probos/cognitive/sub_tasks/compose.py` | `_wr_lookup = context.get("_ward_room_lookup_context", "")` | `_wr_lookup = ""` | C9, C5 |

Uniqueness: rows L6 and L7 name the same line with two different mutants; every other Line cell is distinct. No Line cell is a substring of another line in its file: `return text[:MAX_RENDER_CHARS]` differs from the incomplete branch's `text[: MAX_RENDER_CHARS - ...` by its space, and `if budget <= 0:` from `while budget > 0:`. G1's `if False:` variant is covered by C5 through Q2 and G3.

## 11. Verified Against Codebase (2026-10-22, worktree at `3a94845f`)

```text
query.py:41-57      _query_thread_metadata reads _ctx(context, "thread_id"); get_thread; raises on None
query.py:419-433    _QUERY_OPERATIONS: 13 keys, ends with "oracle_refs": _query_oracle_refs, # AD-462f
query.py:505        operation_keys = [k for k in spec.context_keys if k in _QUERY_OPERATIONS]
query.py:536        success = len(errors) == 0   (a raising operation fails the step)
cognitive_agent.py:340-343   _CHAIN_ELIGIBLE_INTENTS = ward_room_notification, proactive_think
cognitive_agent.py:5616-5682 _maybe_dispatch_oracle_lookup (the pattern copied)
cognitive_agent.py:5685      def _extract_intended_actions(chain_results: list) -> list[str]:
cognitive_agent.py:5754      context_keys=("thread_metadata", "credibility", "self_monitoring", "introspective_telemetry")
cognitive_agent.py:5790      context_keys=("unread_counts", "trust_score")
cognitive_agent.py:6015      async def _execute_chain_with_intent_routing(self, observation: dict) -> dict | None:
cognitive_agent.py:6088      observation["_agent_id"] = getattr(self, 'id', '') or getattr(self, 'agent_type', '')
cognitive_agent.py:6118      observation["_oracle_lookup_fired"] = False  # AD-696 (DLog #4)
cognitive_agent.py:6200-6202 if "oracle_query" in intended_actions: await self._maybe_dispatch_oracle_lookup(...)
cognitive_agent.py:6232-6233 _COMM_ACTIONS = frozenset({...}); has_comm_action = bool(...)
cognitive_agent.py:6329-6336 non-communication actions fall through to the single call (return None)
cognitive_agent.py:8338      _thread_tag = f" (thread {thread_id[:8]})"
cognitive_agent.py:1645      def set_sub_task_executor(self, executor) -> None:
analyze.py:179-189, 214-219  thread prompt: vocabulary, AD-696 instruction, "these 8 keys"
analyze.py:393-401, 430-435  situation prompt: vocabulary, AD-696 instruction, "these 7 keys"
compose.py:408               def _build_user_prompt(context, prior_results) -> str
compose.py:499-507           the _oracle_context section ("+ _oracle" occurs once)
sub_task.py:215-221, 235, 288-298  SubTaskExecutor(config=...), register_handler, execute(...)
sub_task.py:542-549          an optional step with no handler is skipped
sub_task.py:562-569          QUERY receives the full context
threads.py:697-757           get_thread: no archived filter; returns deleted, delete_reason
threads.py:814-837           archive_dm_messages: UPDATE threads SET archived = 1
threads.py:843-972           prune_old_threads: record shape, writer, DELETE posts/threads
threads.py:1002-1006         start_prune_loop stores config and archive_dir
threads.py:1019-1020         month = datetime.now().strftime("%Y-%m"); ward_room_archive_{month}.jsonl
threads.py:1115-1121         _write_archive_sync: json.dumps(record) + "\n", mode "a"
service.py:23-24             from probos.ward_room.channels import ChannelManager / messages import MessageStore
service.py:74-75             _receipt_facts / _visiting_officers lines
service.py:445-449           start_prune_loop / stop_prune_loop delegations
service.py:501-503           get_channel_subscriber_ids (AD-621)
channels.py:129-147          list_channels(agent_id): INNER JOIN memberships
channels.py:208-222          get_channel(channel_id) -> WardRoomChannel | None
channels.py:263-266          get_or_create_dm_channel subscribes both agents
proactive.py:4851-4864       dm-captain channel via create_channel (no subscribe)
communication.py:516-541     AD-621 subscriptions; archive_dir = data_dir / "ward_room_archive"; start_prune_loop
identity.py:154-163, 804     _SOVEREIGN_UUID, is_sovereign_identity_key, resolve_slot_id
visiting_officers.py:62, 325-345   VISITING_AGENT_TYPE = "visiting"; visiting_certificate / is_visiting_identity (get_by_uuid)
config_models/crew.py:275-288      WardRoomConfig: retention_days 7, archive_enabled True, prune_interval_seconds
architecture-baseline.yaml:1010-1017   srp-size WardRoomService triggers [methods]
check_architecture_principles.py:187-188, 937-945   500 lines / 15 methods; TRIGGER DRIFT
wc -l src/probos/ward_room/service.py   521 (class starts at 44)
tests/test_ad643a_intent_routing.py:514-528, tests/test_ad645_composition_briefs.py:56-78   the key-count pins
pyproject.toml:181           asyncio_mode = "auto"
scripts/ad_ceiling.py        CEILING AD-1347, NEXT AD-1348
```

SEARCH uniqueness was checked by Grep in each target file. Each block contains a line that occurs once in its file:
- query.py: lines 411 and 432;
- analyze.py: lines 181, 186-188, 219, 395, 400-401, 435;
- compose.py: lines 505-506;
- cognitive_agent.py: lines 5681, 5685, 6118, 6232-6233;
- service.py: lines 23, 75, 445, 449;
- the two test files: the read ranges above.

## 12. Absence verified (2026-10-22)

| # | Claim | Run | Found | Holds |
|---|---|---|---|---|
| AV1 | Nothing reads the prune archive | Grep `ward_room_archive` in `src/probos` | threads.py:1020, communication.py:540, wardroom_admin.py:41, :44 (all writers or the path) | yes |
| AV2 | Nothing writes `posts.deleted` | Grep `UPDATE posts\|INSERT INTO mod_actions\|delete_post\|soft_delete` in `src/probos`; Grep `deleted` in `ward_room/` | only messages.py:491 (`SET body`); the rest are SELECT filters and the schema | yes |
| AV3 | "Voided" has no Ward Room meaning | Grep `void` in `ward_room/` | channels.py:181 and content_firewall.py:82 ("avoid") | yes |
| AV4 | No test pins `_QUERY_OPERATIONS`' size or keys | Grep `_QUERY_OPERATIONS` in `tests` | test_ad696:19, :41-42 (membership of `oracle_lookup`) | yes |
| AV5 | No test bounds the prompt length | Grep `len\((user\|user_prompt\|prompt)\)\s*[<>]` in `tests` | none | yes |
| AV6 | AD-1347 is not in the roadmap | Grep `AD-1347` in `docs/development/roadmap.md` | none | yes |
| AV7 | No census row or taxonomy entry | Read `ad1343_seam_census.py:25`, `test_ad1343_stop_seam_inventory.py:84-92`, `admission/taxonomy.py:24-36` | stop callees are refusal-shaped; only public coroutines are pinned; no QUERY work kind | yes |

## 13. Deterministic gate checks, resolved up front

- **Precheck:**
  - Test helpers bind constructor results to names (`started`, `built`, `executor`) on which only existing methods are called. `_ward_room`, `_ship` and `_agent` return `Any`, so names like `wr` and `agent` are untyped when they call `lookup_record` and `_maybe_dispatch_ward_room_lookup`.
  - Stand-in classes start with an underscore.
  - The test's raise uses `sqlite3.OperationalError`, which `except sqlite3.OperationalError:` already names in src (service.py:112).
  - The SQL function `substr` is lower case.
- **Architecture:**
  - `WardRoomService` stays under 500 lines.
  - `lookup.py` opens files only with the literal `"rb"`.
  - No `create_task`, and no `sqlite3` or `aiosqlite` connect in src. The one `sqlite3.connect` is in a test.
- **Store registry:** no `CREATE TABLE`.

## 14. Prior Art and Blind Spots

- **Internal, absorbed:**
  - AD-696 is the route.
  - AD-621 is the visibility rule.
  - AD-1229's receipts tool supplied the read-only, ownership-scoped, fail-closed-identity stance (`tools/message_receipts_tool.py:15-21`).
  - BF-907 and BF-903 supply identity.
- **Internal, considered and deferred:** adding a Ward Room lookup type to AD-725's DM one-shot lookup (`cognitive/dm_targeted_lookup.py:25`); it is config-gated, and adding to it widens the slice.
- **External:** Zulip's API states that content access to a direct message requires having sent or received it ([delete-message docs](https://chat.gacrc.uga.edu/api/delete-message)). That is the same participant rule this slice applies to DM channels; absorbed as confirmation. I could not find a primary statement of Matrix's not-found-versus-forbidden rule; not cited.
- **`docs/research/reference-projects.md` (judged on 2026-10-22):** no listed project addresses permission-scoped chat history. Overdue rows (SWE-agent 2026-03-20, AG-UI never) were considered and deferred as unrelated. No row update.
- **Blind spots handled:**
  - 8-character prefixes, not full ids.
  - Archived DMs are still live rows.
  - Captain DM channels have no members.
  - A lookup with no communication action would discard a correct answer (gated).
  - An invisible record must not count toward an ambiguity.
  - A torn tail during a concurrent append.
  - The echo chamber: the frame says "not your memory and not a verdict".
  - A stale fired flag on a reused observation.
- **Blind spots left for the register:** R1-R6 below.

## 15. Diff Reviewer: properties to verify

1. Every record returned or rendered passes the visibility rule. The only grants are membership in `get_channel_subscriber_ids(channel_id)`, or authorship when the channel type is `"dm"`. A missing channel grants nothing.
2. For a given asker and id, an absent record and an invisible one produce equal `LookupResult` fields (apart from `ref`) and equal text with the id substituted.
3. The asker is `_agent_id` only. No path treats a blank, unresolved or visiting id as anyone; no path maps to "captain".
4. The archive reader holds at most `MAX_LINE_BYTES + 1` bytes per read, reads at most `MAX_ARCHIVE_FILES` files and about `MAX_ARCHIVE_BYTES` bytes, writes nothing, and never raises `OSError`.
5. `render_lookup` never exceeds `MAX_RENDER_CHARS`, and never shows the body of a post flagged deleted.
6. `_query_ward_room_lookup` never raises an `Exception` subclass, so the QUERY step's success is unchanged by a Ward Room fault.
7. The dispatch runs at most once per routed chain, only with a communication action, and the fired flag is reset at the start of each routed chain.
8. `WardRoomService`'s class body stays under 500 lines, and `check_architecture_principles.py --check` passes.
9. The updated pins state why they changed; no test was deleted.

## 16. Acceptance criteria

- A1: a member gets a live thread or post by an 8 to 36 character id, with the `#` and upper-case forms accepted.
- A2: a pruned thread or post is found in the archive the real prune wrote, labelled with its prune time.
- A3: visibility as in property 1, for department channels, DMs (live, AD-485-archived and pruned) and Captain DM channels.
- A4: invisible reads as absent (property 2), and only visible records count toward found or ambiguous.
- A5: identity as in property 3.
- A6: an invalid id is typed; ambiguity lists the visible matches; caps hold; deleted posts are flagged.
- A7: an incomplete scan is reported as incomplete (file cap, byte budget, oversized or torn record, unknown directory).
- A8: the operation is registered, never raises, and both ANALYZE prompts teach it.
- A9: C5 passes, crossing ANALYZE to COMPOSE through the real executor, handler, service and archive; C6 and C7 pass.
- Every new test fails on `3a94845f`. The mutation rows are each killed by their named test.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 17. Live-system checks before the build (read-only, `%LOCALAPPDATA%\ProbOS\data`)

1. Whether `ward_room_archive\` exists, how many `ward_room_archive_*.jsonl` files it holds, each file's size, and the largest line in bytes. If any file is over 64 MiB, or a line is over 4 MiB, bring the numbers back before building (D3's bounds, or the deferred index).
2. Whether thread `51d91a7d` is in an archive file (search for `"thread_id": "51d91a7d`), and in which channel. If it is not there, check `ward_room.db` `threads` for `substr(id, 1, 8) = '51d91a7d'`, and posts likewise.
3. `ward_room.archive_enabled` in the live config.
4. The row counts of `threads` and `posts` in `ward_room.db` (the prefix queries scan them).
