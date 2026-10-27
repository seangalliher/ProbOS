"""AD-754: user-directed data erasure manager ("forget this")."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import re
import weakref
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from probos.knowledge.archive_store import ArchiveStore
from probos.security.audit_log import AuditLog
from probos.types import EvictionDisposition

logger = logging.getLogger(__name__)

_ATTACHMENT_ID_RE = re.compile(r"\b[a-f0-9]{64}\b")

# BF-868 (#1343): the ONLY places a genuine attachment id is written into an
# episode. Enumerated against the live tree by walking every ``Episode(`` and
# ``store_episode(`` call in ``src/``, because under-erasing is the worse
# failure of the two -- data the Captain asked to be forgotten surviving is
# worse than an unrelated file being kept.
#
#   anchors.visual_attachment_ref         AD-987 group fan-out
#                                         (thread_fanout.py, types.py:502)
#   outcomes[].attachment_ids             AD-720d-3 Captain-chat vision
#                                         (routers/chat.py)
#   outcomes[].attachment_ref             AD-733 perception anchors
#                                         (routers/perception.py,
#                                          perception/consumer.py)
#   outcomes[].per_attachment_timing[]    AD-720d-1 per-attachment latency
#     .attachment_id                      (dm/reply_pipeline.py, chat.py).
#                                         On the 1:1 DM path this is the ONLY
#                                         carrier -- that episode has no
#                                         ``attachment_ids`` key at all.
#   <metadata>.attachment_id              AD-730-3 image gen
#                                         (cognitive/image_gen_dispatch.py),
#                                         reachable only through the flat
#                                         metadata shape below.
#
# All are typed fields holding bare SHA-256 hex. No production path embeds an
# attachment id in free text, so the free-text scan had no genuine producer to
# serve -- it was pure risk.
_ANCHOR_ATTACHMENT_FIELDS = ("visual_attachment_ref",)
_OUTCOME_ATTACHMENT_KEYS = ("attachment_ids", "attachment_ref", "attachment_refs")
# Outcome keys holding a LIST OF RECORDS, each record carrying an id.
_OUTCOME_RECORD_LIST_KEYS: dict[str, tuple[str, ...]] = {
    "per_attachment_timing": ("attachment_id",),
}
_METADATA_ATTACHMENT_KEYS = ("attachment_id",)

# ``get_episode_metadata`` returns the raw ChromaDB row, which stores
# ``outcomes``/``anchors`` as JSON STRINGS (episodic.py:3550-3557) rather than
# nested objects. Decoded back to the nested shape before extraction.
_FLAT_JSON_FIELDS = (("outcomes_json", "outcomes"), ("anchors_json", "anchors"))


@dataclasses.dataclass(frozen=True)
class ErasureResult:
    count: int
    timestamps: list[str]
    deleted_episode_ids: list[str]
    deleted_attachment_ids: list[str]
    # BF-939 (#1683): each attachment kept because an episode this request did not erase still names it, with those
    # episodes (both sorted). Last, with a default, so every construction stays valid.
    retained_attachments: dict[str, list[str]] = dataclasses.field(default_factory=dict)


class ErasureCascadeIncomplete(Exception):
    """AD-1340: a cascade erased what it could, and some matching episodes are not erased.

    BF-939 (#1683): ``forget_episode`` raises it too, with ``failures`` empty, when its attachment-owner scan failed
    and the episode was erased all the same: an owner the scan did not reach was not checked.

    ``result`` is what was erased, ``failures`` maps each episode id whose erase raised to the original error, and
    ``enumeration_error`` is the first scan failure, the live scan's before the archive's (BF-905); the matches both
    scans found were erased all the same. The message carries counts only: no id and no content.
    """

    def __init__(
        self, result: ErasureResult, failures: dict[str, Exception], enumeration_error: Exception | None,
    ) -> None:
        super().__init__(
            f"erasure_cascade_incomplete:failed={len(failures)},scan_failed={enumeration_error is not None}"
        )
        self.result = result
        self.failures = failures
        self.enumeration_error = enumeration_error


class ArchiveCitationsBlockErasure(Exception):
    """AD-1341 S3 (D8): Ship's Archive entries cite episodes this erasure would erase, so nothing was erased.

    ``entry_ids`` are those entries. The Captain erases each with ``probos archive erase ENTRY_ID --reason TEXT`` and
    retries. The archive is append-only for agents and services, so this path never erases an entry itself; and
    erasing the episodes first would leave entries citing them that no later scan could find. The message carries the
    count only.
    """

    def __init__(self, entry_ids: tuple[int, ...]) -> None:
        super().__init__(f"archive_entries_cite_erased_episodes:count={len(entry_ids)}")
        self.entry_ids = entry_ids


async def _refuse_while_the_archive_cites(archive: ArchiveStore | None, episode_ids: list[str]) -> None:
    """AD-1341 S3 (D8, D10): raise ``ArchiveCitationsBlockErasure`` before anything is erased if an entry cites one.

    No open archive (disabled, failed at boot, or closed at shutdown): nothing to check, as before S3. A failed read
    propagates, so the erasure stops with nothing erased. A module function, so ``ErasureManager`` stays within its
    15-method SRP trigger.
    """
    if archive is None or not episode_ids:
        return
    citing = await archive.entry_ids_citing(episode_ids)
    if citing:
        raise ArchiveCitationsBlockErasure(citing)


async def _live_episodes(memory: Any) -> AsyncIterator[Any]:
    """BF-905: every live episode, through the memory's fail-closed erasure read ``iter_live_episodes``.

    No fallback to ``list_episodes``: that is AD-689's best-effort backfill read, which returns nothing for a stopped
    store or a failed read and skips rows it cannot rebuild. A memory without ``iter_live_episodes`` cannot be scanned,
    so its ``AttributeError`` becomes the live scan's error and the cascade raises after erasing what the archive scan
    found. A module function, not a method: ``ErasureManager`` stays within the SRP review trigger of 15 direct methods.
    """
    async for episode in memory.iter_live_episodes():
        yield episode


@dataclasses.dataclass
class _RecordingFailures:
    """BF-939 (A-4): the first error recording an episode's attachment owners raised, and how many episodes failed."""

    first: Exception | None = None
    count: int = 0


def _recording_owners(
    matches: Callable[[Any], bool],
    owners: dict[str, set[str]],
    attachment_ids_of: Callable[[Any], set[str]],
    wanted: set[str] | None,
    failures: _RecordingFailures,
) -> Callable[[Any], bool]:
    """BF-939 (#1683): ``matches``, also recording each scanned episode as an owner of the attachment ids it names.

    The scan a cascade already makes is the owner scan, so the check adds no read. Owners are keyed by episode id,
    so an episode's own archived versions never count as another owner. ``wanted`` limits what is recorded (one
    episode's ids, on the single path); None records every id. A module function, so ``ErasureManager`` stays within
    its 15-method SRP trigger.

    A-4: a recording that raises never ends the scan and never skips the episode's own match. The first error and
    the count go in ``failures``; ``_matching_ids`` reports the owner map as incomplete, so the erasure proceeds and
    then raises (D5).
    """

    def predicate(episode: Any) -> bool:
        episode_id = str(getattr(episode, "id", ""))
        if episode_id:
            try:
                named = attachment_ids_of(episode)
            except Exception as exc:  # BF-939 (A-4): recording never ends the scan or skips a match; the caller raises it
                failures.count += 1
                if failures.first is None:
                    failures.first = exc
            else:
                for attachment_id in named if wanted is None else named & wanted:
                    owners.setdefault(attachment_id, set()).add(episode_id)
        return matches(episode)

    return predicate


def _last_turns(owners: Mapping[str, set[str]], request: list[str]) -> dict[str, int]:
    """BF-939: for each attachment id the owner scan saw a request member name, the turn of the last such member."""
    turn_of = {episode_id: index for index, episode_id in enumerate(request)}
    last: dict[str, int] = {}
    for attachment_id, named in owners.items():
        turns = [turn_of[episode_id] for episode_id in named if episode_id in turn_of]
        if turns:
            last[attachment_id] = max(turns)
    return last


def _decide_attachments(
    turn: int,
    candidates: set[str],
    owners: Mapping[str, set[str]],
    last_turns: Mapping[str, int],
    request: set[str],
    intact: set[str],
) -> tuple[set[str], dict[str, list[str]]]:
    """BF-939 (#1683): which attachments to unlink in this turn, and which to keep, with the episodes holding each.

    An attachment is decided in the turn of the last request member that names it (``last_turns``; one only this
    member's own records name is decided now), before that member is erased, so AD-1340's order (unlink, then
    evict) holds for the member that decides it. It is unlinked unless an episode outside the request, or a member
    left whole (``intact``: refused, or failed before its erase began), still names it; then it is kept and
    reported. ``owners`` maps an attachment id to every scanned episode id naming it.
    """
    unlink: set[str] = set()
    kept: dict[str, list[str]] = {}
    for attachment_id in sorted(candidates):
        if last_turns.get(attachment_id, turn) > turn:
            continue  # BF-939: a later member names it and decides it in its own turn
        named = owners.get(attachment_id, set())
        holders = (named - request) | (named & intact)
        if holders:
            kept[attachment_id] = sorted(holders)
        else:
            unlink.add(attachment_id)
    return unlink, kept


async def _unlink_attachments(store: Any | None, attachment_ids: set[str]) -> list[str]:
    """Unlink each attachment; return the sorted ids the store reported as removed (BF-939: was a manager method)."""
    if store is None:
        return []
    unlinked: list[str] = []
    for attachment_id in sorted(attachment_ids):
        if await store.unlink(attachment_id):
            unlinked.append(attachment_id)
    return unlinked


# BF-939 (A-4): one erasure lock per episodic memory, shared by every ErasureManager built on it (the route builds one
# per request). Weakly keyed, so an entry goes with its memory; the value holds the lock's loop, never the memory.
_ERASURE_LOCKS: weakref.WeakKeyDictionary[Any, tuple[asyncio.AbstractEventLoop, asyncio.Lock]] = (
    weakref.WeakKeyDictionary()
)


def _one_erasure_at_a_time(memory: Any | None) -> contextlib.AbstractAsyncContextManager[Any]:
    """BF-939 (A-4): hold this around a whole erasure on ``memory``: its checks, scan, decision, unlink and evict.

    Two overlapping erasures that each scanned before the other erased would each keep a shared attachment for the
    episode the other erases, and leave a file no record names. One at a time, each sees the other's finished
    erasure. Not re-entrant: no public erasure method calls another. Taken before, never inside, the memory's store
    write lock (``evict_by_ids`` takes that one). It does not serialize ``store()`` (register G2) or the attachment
    store's other lifetimes (G9). An ``asyncio.Lock`` binds to the first loop it waits on, so a new loop gets a new
    lock (``agents/http_fetch.py`` keys its locks by loop for the same reason). No memory, nothing to serialize.

    A-5: ``memory`` keys a weak registry, so it must be hashable and weakly referenceable (every memory in use is).
    One loop at a time holds a memory's entry: erasures on one memory from two event loops running at once are not
    serialized with each other (production runs one loop; register G10).
    """
    if memory is None:  # BF-939 (A-4): no memory, nothing to serialize
        return contextlib.nullcontext()
    loop = asyncio.get_running_loop()
    held = _ERASURE_LOCKS.get(memory)
    if held is None or held[0] is not loop:
        held = (loop, asyncio.Lock())
        _ERASURE_LOCKS[memory] = held
    return held[1]


class ExitNotesBlockErasure(Exception):
    """AD-1341 S4 (D14): exit notes the next reset would archive cite episodes this erasure would erase; none erased.

    ``paths`` are those notes' Ship's Records paths. The Captain vetoes each with ``probos archive veto PATH --reason
    TEXT``, so it is never archived, and retries. Ship's Records are the crew's documents, so this path never edits a
    note. The message carries the count only.
    """

    def __init__(self, paths: tuple[str, ...]) -> None:
        super().__init__(f"exit_notes_cite_erased_episodes:count={len(paths)}")
        self.paths = paths


def _refuse_while_an_exit_note_cites(citations: Mapping[str, tuple[str, ...]] | None, episode_ids: list[str]) -> None:
    """AD-1341 S4 (D14): raise ``ExitNotesBlockErasure`` before anything is erased if a pending exit note cites one.

    ``citations`` (episode id -> the notes citing it) is read once per request, before the manager is built
    (``archive_promotion.exit_note_citations``); None checks nothing. A module function, so ``ErasureManager`` stays
    within its 15-method SRP trigger.
    """
    if not citations or not episode_ids:
        return
    paths = tuple(sorted({path for episode_id in episode_ids for path in citations.get(episode_id, ())}))
    if paths:
        raise ExitNotesBlockErasure(paths)


class ErasureManager:
    def __init__(
        self,
        episodic_memory: Any | None,
        attachment_store: Any | None,
        audit_log: AuditLog | None,
        *,
        archive_store: ArchiveStore | None = None,
        exit_note_citations: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._episodic_memory = episodic_memory
        self._attachment_store = attachment_store
        self._audit_log = audit_log
        # AD-1341 S4: episode id -> the exit notes awaiting promotion that cite it, read once by the route; None checks nothing
        self._exit_note_citations = exit_note_citations
        # AD-1341 S3: the open Ship's Archive, read only to refuse an erasure while an entry cites its episodes
        self._archive_store = archive_store

    async def forget_episode(self, episode_id: str, reason: str = "user_request") -> ErasureResult:
        """Delete one episode and the attachments no other episode names, then mark audit rows.

        The attachments are unlinked BEFORE the episode is erased (AD-1340): delete what a record names before
        you delete the record. The attachment ids exist only in the episode's own records, and a failed erase may
        already have removed them when it raises (``_erase_ids`` tries every phase before raising), so a retry might
        never find them again. ``mark_deleted`` runs only after a successful erase; an erase failure is raised as the
        original typed error, unwrapped.

        BF-939 (#1683): the attachment store is content-addressed, so one file can hold bytes several episodes name.
        An attachment another live or archived episode still names is kept, and listed in ``retained_attachments``
        with those episodes; it goes when the last episode naming it is erased. Only when this episode names an
        attachment are the live and archived episodes scanned, once, for the other owners. Owners outside episodic
        memory (thread pins, chat, work items, artifacts) are not checked: an attachment only they hold is unlinked,
        as before. If the scan fails, the episode is still erased, an attachment is kept only for an owner the scan
        reached, and ``ErasureCascadeIncomplete`` is raised after the erase (under-erasing is the worse failure,
        BF-868).

        A-4: erasures on one episodic memory run one at a time, whichever manager runs them, so two overlapping
        requests never each keep a shared attachment for the episode the other erases; a request may wait for one
        already running. An owner recording that raises counts as a failed scan, and the scan goes on past it. A
        concurrent ``store()`` is not serialized (register G2).
        """
        async with _one_erasure_at_a_time(self._episodic_memory):  # BF-939 (A-4): scan, decide and erase as one
            await _refuse_while_the_archive_cites(self._archive_store, [episode_id])  # AD-1341 S3: before anything is erased
            _refuse_while_an_exit_note_cites(self._exit_note_citations, [episode_id])  # AD-1341 S4: before anything is erased
            attachment_ids = await self._attachment_ids_for_episode(episode_id)
            owners: dict[str, set[str]] = {}
            scan_error: Exception | None = None
            if attachment_ids and self._attachment_store is not None:  # BF-939: one owner scan, only when a blob could go
                _found, scan_error = await self._matching_ids(lambda _episode: False, owners, attachment_ids)
            unlink, kept = _decide_attachments(0, attachment_ids, owners, {}, {episode_id}, set())
            result = await self._erase_episode(episode_id, reason, unlink, kept)
        if scan_error is not None:
            logger.warning(
                "BF-939: the attachment-owner scan failed, so an owner it did not reach was not checked; "
                "the episode was erased and the failure is raised",
            )
            raise ErasureCascadeIncomplete(result, {}, scan_error) from scan_error
        return result

    async def _erase_episode(
        self, episode_id: str, reason: str, unlink: set[str], kept: dict[str, list[str]],
    ) -> ErasureResult:
        """Unlink ``unlink``, erase the episode, then mark its audit rows; ``kept`` is reported (BF-939).

        The one erase path of ``forget_episode`` and the cascades, after their checks, so AD-1340's order (unlink,
        then evict) is written once.
        """
        unlinked = await _unlink_attachments(self._attachment_store, unlink)
        deleted_episodes = 0
        if self._episodic_memory is not None and hasattr(self._episodic_memory, "evict_by_ids"):
            # AD-1340: erasure is explicit, never derived from the caller's
            # free-text reason (routers/security.py:23,73).
            deleted_episodes = int(
                await self._episodic_memory.evict_by_ids(
                    [episode_id], reason=reason, disposition=EvictionDisposition.ERASE,
                )
            )

        if self._audit_log is not None:
            await self._audit_log.mark_deleted(episode_id)

        return ErasureResult(
            count=deleted_episodes + len(unlinked),
            timestamps=[self._now_iso()],
            deleted_episode_ids=[episode_id] if deleted_episodes > 0 else [],
            deleted_attachment_ids=unlinked,
            retained_attachments=kept,
        )

    async def forget_resource(self, resource_path: str) -> ErasureResult:
        """Delete all episodes that mention a resource path.

        Erases every match it can and raises ``ErasureCascadeIncomplete`` if any did not erase. AD-1341 S3: erases
        nothing, raising ``ArchiveCitationsBlockErasure``, while a Ship's Archive entry cites a match.
        """
        needle = resource_path.lower()

        def mentions_resource(episode: Any) -> bool:
            serialized = json.dumps(self._episode_to_dict(episode), sort_keys=True, default=str).lower()
            return needle in serialized

        async with _one_erasure_at_a_time(self._episodic_memory):  # BF-939 (A-4): a resource's scan and erasures as one
            owners: dict[str, set[str]] = {}  # BF-939: the same scan records every episode's attachments
            matching_ids, enumeration_error = await self._matching_ids(mentions_resource, owners)
            await _refuse_while_the_archive_cites(self._archive_store, matching_ids)  # AD-1341 S3: a resource's matches
            return await self._forget_all(matching_ids, enumeration_error, owners)

    async def forget_agent_memory(self, agent_id: str) -> ErasureResult:
        """Delete all episodes involving a specific agent.

        Erases every match it can and raises ``ErasureCascadeIncomplete`` if any did not erase. AD-1341 S3: erases
        nothing, raising ``ArchiveCitationsBlockErasure``, while a Ship's Archive entry cites a match; an entry the
        agent authored that cites none of them does not block it (D9).
        """

        def involves_agent(episode: Any) -> bool:
            return agent_id in list(getattr(episode, "agent_ids", []) or [])

        async with _one_erasure_at_a_time(self._episodic_memory):  # BF-939 (A-4): an agent's scan and erasures as one
            owners: dict[str, set[str]] = {}  # BF-939: the same scan records every episode's attachments
            matching_ids, enumeration_error = await self._matching_ids(involves_agent, owners)
            await _refuse_while_the_archive_cites(self._archive_store, matching_ids)  # AD-1341 S3: an agent's matches
            return await self._forget_all(matching_ids, enumeration_error, owners)

    async def _matching_ids(
        self, matches: Callable[[Any], bool], owners: dict[str, set[str]] | None = None, wanted: set[str] | None = None,
    ) -> tuple[list[str], Exception | None]:
        """The ids of the candidate episodes ``matches`` accepts, and the first error that cut a scan short, if any.

        BF-905: the live store and the archive are scanned separately, live first, so a failure of one never skips
        the other. A failed scan keeps the matches it found before failing; the caller erases every match from both
        scans, then raises ``ErasureCascadeIncomplete`` carrying the FIRST scan error (``_scan`` logs each at ERROR).
        Under-erasing is the worse failure (BF-868). An archived version is NOT dropped because its id is also live
        (AD-1340 R1): deterministic ids can have a live rewrite that differs from the archived version, and the
        predicate must see both; duplicate ids are removed here.

        BF-939 (#1683): with ``owners``, every scanned episode's declared attachment ids (only the ``wanted`` ones, if
        given) are recorded in it by episode id, in this same pass, so the owner check adds no read. A-4: only with an
        attachment store wired (without one nothing can be unlinked, so the scan is the base's); a recording that
        raises never ends the scan, and is the error returned when neither scan failed.
        """
        memory = self._episodic_memory
        if memory is None:
            return [], None  # F-130 (#1523) owns the unwired case: no episodic memory, nothing to scan
        failures = _RecordingFailures()  # BF-939 (A-4): what the owner recording raised, if anything
        if owners is not None and self._attachment_store is not None:  # BF-939: one pass both matches and records each episode's attachment owners
            matches = _recording_owners(
                matches, owners, lambda episode: self._extract_attachment_ids(self._episode_to_dict(episode)), wanted,
                failures,
            )
        live, live_error = await self._scan("live", _live_episodes(memory), matches)
        archived, archive_error = await self._scan("archive", self._archived_episodes(), matches)
        enumeration_error = live_error if live_error is not None else archive_error
        if failures.first is not None:
            logger.warning(
                "BF-939: recording the attachment owners of %d scanned episode(s) failed (%s); they were still "
                "matched, the owner map is incomplete, and the failure is raised after the erasure",
                failures.count, type(failures.first).__name__,
            )
        if enumeration_error is None and failures.first is not None:
            enumeration_error = failures.first  # BF-939 (A-4): the scans' own errors first, then the recording's
        found = live + archived
        return list(dict.fromkeys(episode_id for episode_id in found if episode_id)), enumeration_error

    async def _scan(
        self, store: str, episodes: AsyncIterator[Any], matches: Callable[[Any], bool],
    ) -> tuple[list[str], Exception | None]:
        """BF-905: the ids ``matches`` accepts in one store's scan, and the error that cut it short, if any."""
        found: list[str] = []
        try:
            async for episode in episodes:
                if matches(episode):
                    found.append(str(getattr(episode, "id", "")))
        except Exception as exc:
            logger.error(
                "BF-905: the %s erasure scan failed after finding %d match(es); "
                "they are erased, then the failure is raised",
                store, len(found), exc_info=True,
            )
            return found, exc  # BF-905: the matches found before the failure are still erased
        return found, None

    async def _forget_all(
        self, episode_ids: list[str], enumeration_error: Exception | None, owners: dict[str, set[str]],
    ) -> ErasureResult:
        """Erase each episode in turn; raise ``ErasureCascadeIncomplete`` if the scan or any erase failed.

        BF-939 (#1683): ``owners`` maps each attachment id the scan saw to every episode naming it. Each match passes
        the per-episode checks ``forget_episode`` makes, then the one erase path, with no second owner scan. An
        attachment is decided in the turn of the last match naming it: unlinked unless an episode outside the
        matches, or a match left whole (refused, or failed before its erase began), still names it; then it is kept
        and reported in ``retained_attachments``. After a failed scan the map is incomplete, and an attachment is
        unlinked when every owner the scan reached is a match (under-erasing is the worse failure, BF-868).
        """
        _refuse_while_an_exit_note_cites(self._exit_note_citations, episode_ids)  # AD-1341 S4: a scan's matches, first
        if enumeration_error is not None and owners:
            logger.warning(
                "BF-939: the erasure scan failed, so the attachment-owner map is incomplete; an attachment is "
                "unlinked when every owner the scan reached is erased by this request",
            )
        request = set(episode_ids)
        last_turns = _last_turns(owners, episode_ids)
        due: dict[int, set[str]] = {}
        for attachment_id, last_turn in last_turns.items():
            due.setdefault(last_turn, set()).add(attachment_id)
        decided: set[str] = set()
        intact: set[str] = set()
        retained: dict[str, set[str]] = {}
        total_count = 0
        deleted_episodes: list[str] = []
        deleted_attachments: set[str] = set()
        failures: dict[str, Exception] = {}
        for turn, episode_id in enumerate(episode_ids):
            began = False
            try:
                # AD-1341 S3 (D10) and S4: the per-episode checks forget_episode makes, unchanged (S4 register R17)
                await _refuse_while_the_archive_cites(self._archive_store, [episode_id])
                _refuse_while_an_exit_note_cites(self._exit_note_citations, [episode_id])
                attachment_ids = await self._attachment_ids_for_episode(episode_id)
                candidates = (attachment_ids | due.get(turn, set())) - decided
                unlink, kept = _decide_attachments(turn, candidates, owners, last_turns, request, intact)
                decided |= unlink | set(kept)
                for attachment_id, holders in kept.items():
                    retained.setdefault(attachment_id, set()).update(holders)
                began = True
                result = await self._erase_episode(episode_id, "user_request", unlink, kept)
            except Exception as exc:
                failures[episode_id] = exc  # erase the rest, then raise one error naming every failure
                if not began:
                    intact.add(episode_id)  # BF-939: its records stand, so it still holds what it names
                logger.error(
                    "AD-1340: erasing episode %s failed: %r; "
                    "the remaining episodes are still erased, then the failure is raised",
                    episode_id, exc,
                )
                continue
            total_count += result.count
            deleted_episodes.extend(result.deleted_episode_ids)
            deleted_attachments.update(result.deleted_attachment_ids)

        erased = ErasureResult(
            count=total_count,
            timestamps=[self._now_iso()],
            deleted_episode_ids=deleted_episodes,
            deleted_attachment_ids=sorted(deleted_attachments),
            retained_attachments={key: sorted(value) for key, value in sorted(retained.items())},
        )
        if failures or enumeration_error is not None:
            cause = enumeration_error if enumeration_error is not None else next(iter(failures.values()))
            raise ErasureCascadeIncomplete(erased, failures, enumeration_error) from cause
        return erased

    async def _archived_episodes(self) -> AsyncIterator[Any]:
        """Every archived version (AD-1340 R1); ``iter_archived_episodes`` already fails closed.

        Under-erasing is the worse failure (BF-868): a cascade that skipped the archive would leave the Captain's
        forgotten episode recoverable.
        """
        if self._episodic_memory is None or not hasattr(self._episodic_memory, "iter_archived_episodes"):
            return
        async for episode in self._episodic_memory.iter_archived_episodes():
            yield episode  # every archived version: the predicate decides, _matching_ids deduplicates

    async def _attachment_ids_for_episode(self, episode_id: str) -> set[str]:
        """Collect every attachment id this episode declares.

        BF-868 reachability scope, recorded rather than left to be rediscovered.
        The metadata fallback runs ONLY when ``get_by_ids`` yields nothing, so a
        producer that writes into episode METADATA (rather than into the
        ``Episode`` dataclass) is seen on this path and not through the
        ``forget_resource`` / ``forget_agent_memory`` cascades -- those rehydrate
        a dataclass, which is a non-empty payload, so the fallback never runs.

        Accepted deliberately rather than fixed by querying both stores for
        every episode, which would add a second round trip per episode to every
        cascade. The only metadata-shaped producer is AD-730-3 image generation,
        and it is currently DEAD at the write side: it is guarded by
        ``hasattr(episodic, "store_episode")`` and ``EpisodicMemory`` has no
        such method (verified by execution, twice). The key is still extracted
        so that repairing that guard does not silently reintroduce an
        under-erase.

        If a live metadata-shaped producer ever appears, merge the two payloads
        here instead of treating them as alternatives.

        AD-1340 R1: every archived version's raw metadata is always added.
        """
        if self._episodic_memory is None:
            return set()

        episode_payload: dict[str, Any] = {}
        if hasattr(self._episodic_memory, "get_by_ids"):
            found = await self._episodic_memory.get_by_ids([episode_id])
            if found:
                episode_payload = self._episode_to_dict(found[0])
        if not episode_payload and hasattr(self._episodic_memory, "get_episode_metadata"):
            meta = await self._episodic_memory.get_episode_metadata(episode_id)
            if isinstance(meta, dict):
                episode_payload = meta
        # AD-1340 R1: EVERY archived version's raw metadata (the same flat shape
        # _normalize_payload decodes) is always added to the live episode's, not
        # only when the episode is not live: ERASE deletes every archive row for
        # the id, so every version's attachments are in scope.
        ids = self._extract_attachment_ids(episode_payload)
        if hasattr(self._episodic_memory, "get_archived_metadata_versions"):
            for archived_meta in await self._episodic_memory.get_archived_metadata_versions(episode_id):
                ids |= self._extract_attachment_ids(archived_meta)
        return ids

    def _extract_attachment_ids(self, payload: Any) -> set[str]:
        """Read attachment ids from the fields DECLARED to carry them.

        BF-868 (#1343): this used to scan every string anywhere in the payload
        with a bare ``[a-f0-9]{64}`` regex, inferring identity from SHAPE. Any
        coincidentally-shaped token -- a hash-suffixed MCP tool name, a channel
        label, a hex string the Captain typed, a digest an LLM echoed into
        ``outcomes[].response`` -- was treated as an attachment id and unlinked.

        ``AttachmentStore.unlink`` is a HARD delete with no refcount, so one
        wrong id is permanent loss of a file nothing referenced.

        The scan is now keyed on structure instead of shape. Values are still
        shape-CHECKED before use, so a malformed entry in a declared field is
        skipped rather than passed to ``unlink``.

        Known and accepted: an attachment id embedded in free text is no longer
        erased. No production path does that today (enumerated above), and the
        alternative -- deleting unrelated files on a coincidence -- is worse.
        A future producer must write into a declared field, not free prose.
        """
        found: set[str] = set()
        payload = self._normalize_payload(payload)
        if not payload:
            return found

        for key in _METADATA_ATTACHMENT_KEYS:
            found.update(self._ids_from_value(payload.get(key)))

        anchors = payload.get("anchors")
        if isinstance(anchors, dict):
            for field_name in _ANCHOR_ATTACHMENT_FIELDS:
                found.update(self._ids_from_value(anchors.get(field_name)))

        outcomes = payload.get("outcomes")
        if isinstance(outcomes, list):
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    continue
                for key in _OUTCOME_ATTACHMENT_KEYS:
                    found.update(self._ids_from_value(outcome.get(key)))
                for list_key, record_keys in _OUTCOME_RECORD_LIST_KEYS.items():
                    records = outcome.get(list_key)
                    if not isinstance(records, (list, tuple)):
                        continue
                    for record in records:
                        if not isinstance(record, dict):
                            continue
                        for record_key in record_keys:
                            found.update(self._ids_from_value(record.get(record_key)))
        return found

    @staticmethod
    def _normalize_payload(payload: Any) -> dict[str, Any]:
        """Bring the flat ``get_episode_metadata`` row into the nested shape.

        BF-868 (#1343): ``_attachment_ids_for_episode`` has two sources.
        ``get_by_ids`` yields a dataclass, so ``asdict`` gives nested
        ``outcomes``/``anchors``. The ``get_episode_metadata`` fallback yields
        the raw ChromaDB row, where those live as JSON strings under
        ``outcomes_json``/``anchors_json``. Without this decode the fallback
        extracted nothing at all, so any episode reached that way erased zero
        attachments -- silent under-erase.
        """
        if not isinstance(payload, dict):
            return {}
        normalized = dict(payload)
        for json_key, nested_key in _FLAT_JSON_FIELDS:
            if nested_key in normalized:
                continue
            raw = normalized.get(json_key)
            # Empty is the legitimate "no anchors" encoding, not a failure.
            if not isinstance(raw, str) or not raw:
                continue
            try:
                normalized[nested_key] = json.loads(raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                # Degrade rather than raise, but never silently: erasing
                # nothing is the exact failure this decode exists to fix.
                logger.warning(
                    "BF-868: could not decode %s while resolving attachments for "
                    "erasure; that half of the episode contributes no attachment "
                    "ids, so a referenced file may survive the erase",
                    json_key, exc_info=True,
                )
        return normalized

    @staticmethod
    def _ids_from_value(value: Any) -> set[str]:
        """Accept a bare id or a list of them, keeping only well-formed ones.

        ``fullmatch``, not ``search``: a declared field holds an id, so a value
        that merely CONTAINS one is malformed and not something to salvage.
        """
        if isinstance(value, str):
            candidates: list[Any] = [value]
        elif isinstance(value, (list, tuple)):
            candidates = list(value)
        else:
            return set()
        cleaned = (
            item.strip().lower() for item in candidates if isinstance(item, str)
        )
        # Return the CLEANED value, not the original: validating the stripped
        # form and then unlinking the padded one would silently under-erase,
        # because the store never matches a key with surrounding whitespace.
        return {value for value in cleaned if _ATTACHMENT_ID_RE.fullmatch(value)}

    def _episode_to_dict(self, episode: Any) -> dict[str, Any]:
        if dataclasses.is_dataclass(episode):
            return dataclasses.asdict(episode)
        if isinstance(episode, dict):
            return episode
        data = getattr(episode, "__dict__", {})
        return dict(data) if isinstance(data, dict) else {}

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
