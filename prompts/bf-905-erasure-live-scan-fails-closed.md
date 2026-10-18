# BF-905 (#1587): the erasure cascades' live scan fails closed

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-18

**Status:** ready to build. **Base:** the AD-1340 S2a head `01acb85c` (PR #1589); build on `main` once #1589 has merged (no anchor below depends on anything else). **Number:** BF-905, allocated by the issue title; no new AD or BF. **Depends on:** AD-1340 S1 (merged) and S2a (#1589). **Estimated tests:** 12 new in one new file, one existing test extended, three test fakes updated. **Milestones:** one (M1), with a cut point.

One-line summary: `forget_agent_memory` and `forget_resource` read the live store through a new fail-closed reader, `EpisodicMemory.iter_live_episodes`, in a scan of their own, separate from the archive scan. An unreadable live store, a failed ChromaDB read, or a live row that does not rebuild now ends in `ErasureCascadeIncomplete` after every match found has been erased. Until now the cascade reported a clean success.

---

## Problem

`ErasureManager._candidate_episodes` (`src/probos/knowledge/erasure.py:212-226`) reads the live store through `_list_episodes` (`:207-210`), which calls `EpisodicMemory.list_episodes(limit=None)` (`src/probos/cognitive/episodic.py:2216-2247`). That is AD-689's best-effort backfill read:

- with no collection it returns `[]` (`:2224-2225`);
- on any `collection.get` failure it returns `[]` and logs at DEBUG (`:2226-2230`);
- it skips, at DEBUG, every row `_metadata_to_episode` cannot rebuild (`:2241-2246`). That method has unguarded `json.loads` and `AnchorFrame(**...)` calls (`:4297-4298`, `:4360-4367`).

The cascade erases only what it saw. `_forget_all` (`erasure.py:175-205`) then returns a clean `ErasureResult`, and matching live episodes stay in ChromaDB, FTS, the activation log and the participant index.

`stop()` sets `_collection = None` (`episodic.py:1663`, `:1691`) and `_archive_state = "absent"` (`:1685`). A cascade on a stopped memory therefore finds nothing and reports success, while `forget_episode` on the same memory raises `erasure_live_store_unavailable` (`:2788-2789`).

The archive half already fails closed: `iter_archived_episodes` (`:2870-2894`) scans past bad rows, then raises `EpisodeArchiveIntegrityError`. `_matching_ids` (`erasure.py:154-173`) records that as `enumeration_error`, and `_forget_all` raises it (`:202-204`). One generator feeds both halves, so a live failure (if it raised at all) would also skip the archive scan. BF-868's rule applies: under-erasing is the worse failure.

Reach: the Captain's AD-754 route `POST /api/security/forget` (`src/probos/routers/security.py:73-102`), given a transient ChromaDB read failure, a live row whose metadata no longer rebuilds (corruption, or schema drift in `anchors_json`), or a cascade on a stopped memory. P2, erasure integrity: the Captain is told an erasure is complete when it is not.

## Solution overview

1. **`EpisodicMemory.iter_live_episodes(*, page_size=500)`**, an async iterator beside `list_episodes` and the live twin of `iter_archived_episodes`. It raises when there is no collection, lets a ChromaDB failure propagate, reads the ids once and then fetches the rows by id in pages, and yields every row that rebuilds. A row that does not rebuild is logged at WARNING, by id and exception type only. After the scan it raises a count of such rows. It does not sort. `list_episodes` is not changed.
2. **`ErasureManager._matching_ids`** runs two scans, live first, each through a new `_scan` helper with its own accumulator and its own `try`. Every match from both scans is erased. `enumeration_error` carries the first error, and `_scan` logs each failure at ERROR. The live read is called directly, with no `hasattr` fallback, so a memory without `iter_live_episodes` fails closed. "No memory wired" keeps today's empty result (F-130's case).
3. The three test fakes move from `list_episodes` to `iter_live_episodes`. The AD-1293 "erasure can still reach a marked episode" test also covers the new reader.

## Decisions (decided by the Architect; the Captain may overrule any of them afterwards)

- **D1. Re-anchored.** Every anchor below was taken on `01acb85c`. Anchors that moved since the issue (on `28a3786b`) are listed under **Anchors moved** in the Verified section. `erasure.py` did not change between the two trees (`git diff --stat 28a3786b 01acb85c` lists only `episodic.py` and `routers/security.py`).
- **D2. Which failures count as a row that does not rebuild.** Any `Exception` raised by `self._metadata_to_episode(...)` for one row. That matches the archive half (`episodic.py:2883-2891` catches `Exception`). A narrower list such as `(ValueError, TypeError)` would let an unforeseen type abort the scan and hide every later row. That would still fail closed, but it would erase less. Both `collection.get` calls sit outside the per-row `try`, so their failures propagate unwrapped. `BaseException` (cancellation) propagates too.
- **D3. Shape and paging.** An async iterator with `page_size: int = 500` and the same `ValueError` on `page_size < 1` as `EpisodeArchive.iter_records` (`episode_archive.py:601`, `:608-609`). One ids-only `get(include=[])`, then `get(ids=<page>, include=["metadatas", "documents"])` per page.
  - **Not offset paging:** `_iter_collection_pages` (`episodic.py:353-401`) states its own precondition (`:377-383`): a collection that gains or loses rows mid-iteration makes `offset` skip rows. A concurrent eviction during an offset scan could silently skip a live match.
  - **Not one full read:** that would hold every row's metadata and document at once.
  - **Rows that change during the scan:** a row that leaves between the id read and its page fetch is no longer live. If it was archived, the archive scan, which runs after the live one, sees it. A row stored after the id read is outside this cascade, as it is today.
  - **Collection bound once** into a local, so a `stop()` cannot turn a later read into an `AttributeError` on `None`; the closed client's own error propagates instead.
  - **`zip(..., strict=True)`**, so a misaligned ChromaDB result raises rather than truncating. No real store produces a misaligned result, so this is not mutation-tested.
- **D4. A wired memory without `iter_live_episodes` now fails closed.** `_live_episodes(memory)` calls `memory.iter_live_episodes()` directly. The `AttributeError` is raised inside the live `_scan`'s `try`, becomes the live scan's error, the archive scan still runs, and the cascade raises `ErasureCascadeIncomplete`. **No episodic memory wired** (`None`) returns `([], None)` before any scan, which keeps today's empty result: #1523 F-130 owns that case (test T7). For the fakes and the mock:
  - The three test fakes replace `list_episodes` with `iter_live_episodes`. That includes `tests/test_bf869_fused_frame_refs.py`, whose tests never cascade, so that no fake advertises the retired erasure read.
  - `src/probos/cognitive/episodic_mock.py` is **unchanged**. It is never wired to an `ErasureManager` in `src/`, and it has none of `list_episodes`, `get_by_ids` or `evict_by_ids` (Absence Verified 3). If it ever were wired, a cascade would now raise instead of reporting an empty success, which is the intended outcome.
- **D5. Two scans, one error slot.** `_matching_ids` calls `_scan("live", ...)`, then `_scan("archive", ...)`, unconditionally. `enumeration_error = live_error if live_error is not None else archive_error`. `_scan` logs every failure at ERROR, so the second error of two is logged and not raised (issue acceptance 2).
  - `_live_episodes` is a **module function**, not a method: `ErasureManager` has exactly 15 direct methods today, and `scripts/check_architecture_principles.py` gates on more than 15 (`:188`, `:568`). After the change it still has 15: `_list_episodes` and `_candidate_episodes` are removed; `_scan` and `_archived_episodes` are added.
  - The archive generator keeps S1's guard line and yield line byte for byte, so S1 mutants K2 and V1 still anchor.
- **D6. Route status: 500, route unchanged.** `/forget` has no handler for `ErasureCascadeIncomplete`, and the app has none for `Exception` (Absence Verified 5), so Starlette's server-error middleware answers 500. The same was already true of S1's archive-scan failures through this route. The seam test (T5) uses httpx's ASGI transport with `raise_app_exceptions=False` (its default is `True`, `.venv/Lib/site-packages/httpx/_transports/asgi.py:90`) and asserts status 500 and no success body. A typed 5xx body naming what was erased would change the route's wire contract. That is considered and deferred: the orchestrator may record it on #1523 as a P3 follow-up.
- **D7. The new WARNING carries the id and the exception type name only, with no `exc_info`.** A traceback can echo a metadata value (for example, a float conversion error quotes the string it could not convert). That is stricter than the archive half's `exc_info=True` (`:2887-2890`), which stays unchanged under the issue's Do Not Build.
- **D8. Mutation campaign.** One campaign of record on the final tree (table below), plus re-runs of the S1 rows on `erasure.py`; K7 is retired.

## Section 0: Event types

None. BF-905 adds no `EventType`.

## Section 1 (M1): `src/probos/cognitive/episodic.py`

### 1a. The fail-closed live reader, after `list_episodes`

SEARCH:
```python
            try:
                out.append(self._metadata_to_episode(ep_id, doc or "", meta or {}))
            except Exception:
                logger.debug("AD-689: failed to reconstruct episode %s", ep_id, exc_info=True)
                continue
        return out

    async def get_by_ids(
```
REPLACE:
```python
            try:
                out.append(self._metadata_to_episode(ep_id, doc or "", meta or {}))
            except Exception:
                logger.debug("AD-689: failed to reconstruct episode %s", ep_id, exc_info=True)
                continue
        return out

    async def iter_live_episodes(self, *, page_size: int = 500) -> AsyncIterator[Episode]:
        """BF-905: every live episode, rehydrated (erasure cascades). Fails closed, unlike ``list_episodes``.

        A service read, not a recall surface, and unfiltered: a marked episode must stay erasable (AD-1293).
        ``list_episodes`` stays AD-689's best-effort read for the edge backfill; erasure no longer uses it.

        - No collection (stopped or never started) raises ``erasure_live_store_unavailable``, as ERASE by id does.
        - A ChromaDB read failure propagates, unwrapped.
        - The ids are read once, then the rows are fetched by id in pages of ``page_size``. Offset paging
          (``_iter_collection_pages``) is not used: a row deleted mid-scan would shift the offsets and skip a live
          row unseen. A row that left the store between the two reads is no longer live; if it was archived, the
          archive scan, which the cascade runs after this one, sees it.
        - A row that cannot be rehydrated is logged at WARNING with its id and exception type only (never content,
          and no traceback, which can echo a metadata value) and skipped; after the scan,
          ``erasure_live_rows_unrehydratable:<count>`` is raised, so a cascade never silently leaves a live row out.
        - Not sorted: a cascade needs every row, not an order.
        """
        if page_size < 1:
            raise ValueError("erasure_live_page_size_invalid")
        collection = self._collection  # BF-905: bound once, so a stop() mid-scan is the client's error, never None
        if collection is None:
            raise EpisodeErasureIncomplete("erasure_live_store_unavailable")  # BF-905: a stopped store is never an empty scan
        ids = list(collection.get(include=[])["ids"] or [])
        unreadable_rows = 0
        for start in range(0, len(ids), page_size):
            page = collection.get(ids=ids[start:start + page_size], include=["metadatas", "documents"])
            page_ids = list(page["ids"] or [])
            metas = page.get("metadatas") or [{} for _ in page_ids]
            docs = page.get("documents") or ["" for _ in page_ids]
            for episode_id, meta, doc in zip(page_ids, metas, docs, strict=True):
                try:
                    episode = self._metadata_to_episode(episode_id, doc or "", meta or {})
                except Exception as exc:
                    unreadable_rows += 1
                    logger.warning("BF-905: live episode %s could not be rehydrated (%s); erasure cascades cannot match it", episode_id, type(exc).__name__)
                    continue
                yield episode
        if unreadable_rows:
            raise EpisodeErasureIncomplete(f"erasure_live_rows_unrehydratable:{unreadable_rows}")

    async def get_by_ids(
```

`AsyncIterator` (`:19`), `EpisodeErasureIncomplete` (`:38`), `Episode` (`:48`) and `logger` are already imported or defined; add no import. Keep the `logger.warning(...)` call on **one line** and the two `raise` lines exactly as written: they are mutation anchors.

## Section 2 (M1): `src/probos/knowledge/erasure.py`

### 2a. `ErasureCascadeIncomplete` docstring

SEARCH:
```python
    ``result`` is what was erased, ``failures`` maps each episode id whose erase raised to the original error, and
    ``enumeration_error`` is set when the scan for matches itself failed (the matches found before it were erased).
    The message carries counts only: no id and no content.
```
REPLACE:
```python
    ``result`` is what was erased, ``failures`` maps each episode id whose erase raised to the original error, and
    ``enumeration_error`` is the first scan failure, the live scan's before the archive's (BF-905); the matches both
    scans found were erased all the same. The message carries counts only: no id and no content.
```

### 2b. The live scan's source, a module function

SEARCH:
```python
        self.result = result
        self.failures = failures
        self.enumeration_error = enumeration_error


class ErasureManager:
```
REPLACE:
```python
        self.result = result
        self.failures = failures
        self.enumeration_error = enumeration_error


async def _live_episodes(memory: Any) -> AsyncIterator[Any]:
    """BF-905: every live episode, through the memory's fail-closed erasure read ``iter_live_episodes``.

    No fallback to ``list_episodes``: that is AD-689's best-effort backfill read, which returns nothing for a stopped
    store or a failed read and skips rows it cannot rebuild. A memory without ``iter_live_episodes`` cannot be scanned,
    so its ``AttributeError`` becomes the live scan's error and the cascade raises after erasing what the archive scan
    found. A module function, not a method: ``ErasureManager`` stays within the SRP review trigger of 15 direct methods.
    """
    async for episode in memory.iter_live_episodes():
        yield episode


class ErasureManager:
```

### 2c. Two scans

SEARCH:
```python
    async def _matching_ids(self, matches: Callable[[Any], bool]) -> tuple[list[str], Exception | None]:
        """The ids of the candidate episodes ``matches`` accepts, and the error that cut the scan short, if any.

        A scan that fails (the archive cannot be read) keeps the matches found before it: the caller erases
        them, then raises. Erasing nothing because one store was unreadable would leave every live match behind.
        """
        found: list[str] = []
        enumeration_error: Exception | None = None
        try:
            async for episode in self._candidate_episodes():
                if matches(episode):
                    found.append(str(getattr(episode, "id", "")))
        except Exception as exc:
            logger.error(
                "AD-1340: the erasure scan failed after finding %d match(es); "
                "they are erased, then the failure is raised",
                len(found), exc_info=True,
            )
            enumeration_error = exc  # the archive scan failed: erase the matches found, then raise
        return list(dict.fromkeys(episode_id for episode_id in found if episode_id)), enumeration_error
```
REPLACE:
```python
    async def _matching_ids(self, matches: Callable[[Any], bool]) -> tuple[list[str], Exception | None]:
        """The ids of the candidate episodes ``matches`` accepts, and the first error that cut a scan short, if any.

        BF-905: the live store and the archive are scanned separately, live first, so a failure of one never skips
        the other. A failed scan keeps the matches it found before failing; the caller erases every match from both
        scans, then raises ``ErasureCascadeIncomplete`` carrying the FIRST scan error (``_scan`` logs each at ERROR).
        Under-erasing is the worse failure (BF-868). An archived version is NOT dropped because its id is also live
        (AD-1340 R1): deterministic ids can have a live rewrite that differs from the archived version, and the
        predicate must see both; duplicate ids are removed here.
        """
        memory = self._episodic_memory
        if memory is None:
            return [], None  # F-130 (#1523) owns the unwired case: no episodic memory, nothing to scan
        live, live_error = await self._scan("live", _live_episodes(memory), matches)
        archived, archive_error = await self._scan("archive", self._archived_episodes(), matches)
        enumeration_error = live_error if live_error is not None else archive_error
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
```

### 2d. The archive scan's source (S1's guard and yield lines kept byte for byte)

SEARCH:
```python
    async def _list_episodes(self) -> list[Any]:
        if self._episodic_memory is None or not hasattr(self._episodic_memory, "list_episodes"):
            return []
        return list(await self._episodic_memory.list_episodes(limit=None))

    async def _candidate_episodes(self) -> AsyncIterator[Any]:
        """Every live episode, then every archived version (AD-1340 R1).

        Under-erasing is the worse failure (BF-868): a cascade that skipped the
        archive would leave the Captain's forgotten episode recoverable. An
        archived version is NOT dropped because its id is also live: deterministic
        ids can have a live rewrite that differs from the archived version, and
        the predicate must see both. ``_matching_ids`` removes duplicate ids.
        """
        for episode in await self._list_episodes():
            yield episode
        if self._episodic_memory is None or not hasattr(self._episodic_memory, "iter_archived_episodes"):
            return
        async for episode in self._episodic_memory.iter_archived_episodes():
            yield episode  # every archived version: the predicate decides, _matching_ids deduplicates
```
REPLACE:
```python
    async def _archived_episodes(self) -> AsyncIterator[Any]:
        """Every archived version (AD-1340 R1); ``iter_archived_episodes`` already fails closed.

        Under-erasing is the worse failure (BF-868): a cascade that skipped the archive would leave the Captain's
        forgotten episode recoverable.
        """
        if self._episodic_memory is None or not hasattr(self._episodic_memory, "iter_archived_episodes"):
            return
        async for episode in self._episodic_memory.iter_archived_episodes():
            yield episode  # every archived version: the predicate decides, _matching_ids deduplicates
```

After 2d, `rg -n "_candidate_episodes|_list_episodes|list_episodes" src/probos/knowledge/erasure.py` must print only the `_live_episodes` docstring's mention of `list_episodes`. No other file in `src/` changes.

## Section 3 (M1): the three test fakes

### 3a. `tests/test_erasure_manager.py`, import

SEARCH:
```python
from __future__ import annotations

from dataclasses import dataclass
```
REPLACE:
```python
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
```

### 3b. `tests/test_erasure_manager.py`, the fake's live read

SEARCH:
```python
    async def list_episodes(self, limit: int | None = None) -> list[_Episode]:
        episodes = list(self._episodes.values())
        return episodes if limit is None else episodes[:limit]
```
REPLACE:
```python
    async def iter_live_episodes(self) -> AsyncIterator[_Episode]:
        """BF-905: the erasure cascades' live read (``list_episodes`` is no longer an erasure read)."""
        for episode in list(self._episodes.values()):
            yield episode
```

### 3c. `tests/test_erasure_manager.py`, the test that read the fake back

SEARCH:
```python
    remaining = await episodic.list_episodes()
    assert {episode.id for episode in remaining} == {"ep-2"}
```
REPLACE:
```python
    assert {episode.id async for episode in episodic.iter_live_episodes()} == {"ep-2"}
```

### 3d. `tests/test_bf868_erasure_declared_fields.py`, import

SEARCH:
```python
import dataclasses
import json
import logging

import pytest
```
REPLACE:
```python
import dataclasses
import json
import logging
from collections.abc import AsyncIterator

import pytest
```

### 3e. `tests/test_bf868_erasure_declared_fields.py`, the fake's live read

SEARCH:
```python
    async def list_episodes(self, limit: int | None = None) -> list[_Episode]:
        return list(self._episodes)
```
REPLACE:
```python
    async def iter_live_episodes(self) -> AsyncIterator[_Episode]:
        """BF-905: the erasure cascades' live read."""
        for episode in list(self._episodes):
            yield episode
```

### 3f. `tests/test_bf869_fused_frame_refs.py`, import

SEARCH:
```python
import dataclasses
import hashlib
from io import BytesIO
```
REPLACE:
```python
import dataclasses
import hashlib
from collections.abc import AsyncIterator
from io import BytesIO
```

### 3g. `tests/test_bf869_fused_frame_refs.py`, the fake's live read

SEARCH:
```python
    async def list_episodes(self, limit: int | None = None) -> list:
        return list(self._episodes)
```
REPLACE:
```python
    async def iter_live_episodes(self) -> AsyncIterator:
        """BF-905: the erasure cascades' live read."""
        for episode in list(self._episodes):
            yield episode
```

## Section 4 (M1): `tests/test_ad1293_turn_record_reaches_episode.py`

The property this test owns (a marked episode stays erasable) moves with the erasure read, so the test now asserts it for both reads. Its name is kept, so the test id stays stable.

SEARCH:
```python
async def test_list_episodes_is_unfiltered_so_erasure_can_still_reach_it(mem) -> None:
    """``list_episodes`` backs ``knowledge/erasure.py`` and
    ``knowledge/backfill.py``. Filtering it would make a marked episode
    un-erasable -- a data-integrity defect, not a safety control."""
    await _store_both(mem)

    assert "marked-1" in {e.id for e in await mem.list_episodes()}
```
REPLACE:
```python
async def test_list_episodes_is_unfiltered_so_erasure_can_still_reach_it(mem) -> None:
    """``list_episodes`` backs ``knowledge/backfill.py``, and BF-905's
    ``iter_live_episodes`` backs ``knowledge/erasure.py``. Filtering either
    would make a marked episode un-erasable -- a data-integrity defect, not a
    safety control."""
    await _store_both(mem)

    assert "marked-1" in {e.id for e in await mem.list_episodes()}
    assert "marked-1" in {e.id async for e in mem.iter_live_episodes()}
```

## Section 5 (M1): `tests/test_bf905_erasure_live_scan.py` (new)

Module docstring: BF-905 (#1587). It uses a real `EpisodicMemory` (real ChromaDB, FTS5, `ActivationTracker`, `ParticipantIndex`, `EvictionAuditLog`) on `tmp_path`, built by S1's rig. A failed ChromaDB read is injected by a forwarding proxy on the real collection (S1's `_CollectionProxy` pattern). An unrehydratable row is a real row whose stored metadata no longer rebuilds. Nothing mocks the erasure manager, the memory or the route. Every test asserts its premise first. `asyncio_mode = "auto"` (`pyproject.toml:181`), so no asyncio marks are needed.

Imports:
- From `tests.test_ad1340_s1_eviction`: `_episode`, `_ids`, `_memory`, `_raw`, `_record_collection`.
- From `tests.test_ad1340_s1_erasure`: `_ARCHIVED_TRACES`, `_GONE`, `_LIVE_TRACES`, `_manager`, `_seed`, `_traces`.
- From `tests.test_ad1340_s2a_lookup_route`: `_runtime`.
- From `probos.cognitive.episode_archive`: `ARCHIVE_FILENAME`, `EpisodeErasureIncomplete`.
- Also `probos.api.create_app`, `probos.cognitive.episodic.EpisodicMemory`, `probos.knowledge.erasure.ErasureCascadeIncomplete` / `ErasureManager` / `ErasureResult`, and `probos.types.Episode` / `EpisodeStoreOutcome`.

Helpers, verbatim:

```python
class _ScanReadFault:
    """Forwards to the real collection; the first ``get`` called without ``ids`` (the live scan's id read) raises once."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.fired = False

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self.inner, name)
        if name != "get":
            return attribute

        def _get(*args: Any, **kwargs: Any) -> Any:
            if not self.fired and "ids" not in kwargs:
                self.fired = True
                raise RuntimeError("injected: the live scan read failed")
            return attribute(*args, **kwargs)

        return _get


def _fail_the_next_scan_read(em: EpisodicMemory) -> _ScanReadFault:
    """Interpose the fault on the live collection (test-only private access, as S1's ``_record_collection``)."""
    fault = _ScanReadFault(em._collection)
    em._collection = fault
    return fault


def _scene() -> tuple[Episode, Episode, Episode, Episode]:
    """L live and A archived (agent-a, the controls); B1 live and B2 archived (agent-b, the target)."""
    return (
        _episode(0),
        _episode(1),
        dataclasses.replace(_episode(2), agent_ids=["agent-b"]),
        dataclasses.replace(_episode(3), agent_ids=["agent-b"]),
    )


def _errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "probos.knowledge.erasure" and r.levelno == logging.ERROR]
```

`_route_client(em, root)` is an async context manager that builds the app with `create_app(_runtime(root, em))`, wraps it in httpx's ASGI transport with `raise_app_exceptions=False`, and opens an httpx async client on it with `base_url="http://test"`, in the test's own event loop. It is S2a's `_client` (`tests/test_ad1340_s2a_lookup_route.py:213-219`) plus that one flag; S2a's `_runtime` already sets `_data_dir`.

"Seed" means `await _seed(rig, [L, A, B1, B2], archive=[A.id, B2.id])` inside `async with _memory(tmp_path, "archive") as rig`. `_seed` itself asserts every episode's traces (the premise). "Traces" means `await _traces(em, rig.root, eid, agent=<the episode's agent>)`.

| ID | Test | Premise (asserted first) | Asserts |
|---|---|---|---|
| R1 | `test_the_live_read_refuses_a_memory_that_was_never_started` | Construct an `EpisodicMemory` (`db_path=tmp_path / "chroma" / "episodes.db"`, `max_episodes=100`, `relevance_threshold=0.0`) and never start it. `await em.list_episodes() == []`: the old read reports an empty store. | Iterating `em.iter_live_episodes()` raises `EpisodeErasureIncomplete` matching `^erasure_live_store_unavailable$`. |
| R2 | `test_the_live_read_pages_by_id_and_yields_every_row_once` | Store `_episode(0..4)` (each `STORED`). `len(_raw(em, _ids(5))["ids"]) == 5`. | `proxy = _record_collection(em)`. Ids from `iter_live_episodes(page_size=2)`: sorted equals `_ids(5)` and length 5. `proxy.calls.count(("get", [])) == 1` and `proxy.calls.count(("get", ["metadatas", "documents"])) == 3`. |
| R3 | `test_the_live_read_refuses_a_page_size_below_one` | Started rig; one episode stored. | `iter_live_episodes(page_size=0)` raises `ValueError` matching `^erasure_live_page_size_invalid$`. |
| R4 | `test_a_failed_live_read_propagates_unwrapped` | One episode stored and live (`_raw`). | With `_fail_the_next_scan_read(em)`, iterating raises `RuntimeError` matching `^injected: the live scan read failed$`, and `fault.fired`. |
| T1 | `test_a_failed_live_read_still_erases_the_archived_matches_then_raises` (acceptance i) | Seed. The ids from `iter_live_episodes()`, sorted, equal `sorted([L.id, B1.id])`. | Install the fault. `forget_agent_memory("agent-b")` raises `ErasureCascadeIncomplete`. `fault.fired`. `str(enumeration_error) == "injected: the live scan read failed"`. `failures == {}`. `result.deleted_episode_ids == [B2.id]`. B2 traces `_GONE`. B1 `_LIVE_TRACES`: the report is true. L `_LIVE_TRACES`, A `_ARCHIVED_TRACES`. Then a retry, with the fault spent, returns `deleted_episode_ids == [B1.id]` and B1 is `_GONE`. |
| T2 | `test_a_live_row_that_cannot_rehydrate_is_reported_and_the_rest_erased` (ii) | Seed `[L, B1, X, B2]`, archive `[B2.id]`, where X is `_episode(4)` with `agent_ids=["agent-b"]`. Corrupt X in place: `meta = _raw(em, [X.id])["metadatas"][0]`, then `em._collection.update(ids=[X.id], metadatas=[{**meta, "anchors_json": json.dumps({"retired_field": "drift"})}])` (schema drift, so the frozen `AnchorFrame` rejects it). `_raw(em, [X.id])["ids"] == [X.id]` and `X.id not in {e.id for e in await em.list_episodes()}`: the old read dropped it silently. | `caplog.set_level(logging.WARNING)`. `forget_agent_memory("agent-b")` raises `ErasureCascadeIncomplete`. `enumeration_error` is an `EpisodeErasureIncomplete` with `str == "erasure_live_rows_unrehydratable:1"`. `failures == {}`. Sorted `deleted_episode_ids == sorted([B1.id, B2.id])`; both `_GONE`. X `_LIVE_TRACES` (agent-b). Exactly one WARNING record from `probos.cognitive.episodic` contains `X.id`. It contains `"TypeError"`, has `exc_info is None`, and does not contain `X.user_input`. |
| T3 | `test_a_cascade_on_a_stopped_memory_raises` (iii) | Seed `[L, A]`, archive `[A.id]`. `await em.stop()`. `await em.list_episodes() == []` and `em.archive_available is False`. | `forget_agent_memory("agent-a")` raises `ErasureCascadeIncomplete`. `enumeration_error` is an `EpisodeErasureIncomplete` with `str == "erasure_live_store_unavailable"`. `failures == {}`. `result.deleted_episode_ids == []`. `forget_episode(L.id)` raises `EpisodeErasureIncomplete` matching `erasure_live_store_unavailable`: the two entry points now agree. |
| T4 | `test_a_healthy_cascade_is_unchanged` (iv) | Seed. | `caplog.set_level(logging.WARNING)`. `forget_agent_memory("agent-b")` returns sorted `deleted_episode_ids == sorted([B1.id, B2.id])`; B1 and B2 `_GONE` (every store at zero); L `_LIVE_TRACES`, A `_ARCHIVED_TRACES`. No record contains `"BF-905"`. |
| T5 | `test_the_forget_route_answers_500_when_the_live_scan_fails` (v) | Seed. `caplog.set_level(logging.ERROR)`. | Inside `_route_client(em, tmp_path)`, install the fault and POST `/api/security/forget` with `{"agent_id": "agent-b"}`. `fault.fired`. `status_code == 500`. `"deleted_episode_ids" not in response.text`. B2 `_GONE`; B1 `_LIVE_TRACES`; L and A unchanged. One `_errors(caplog)` message contains `"the live erasure scan failed"`. A second POST returns 200 with `json()["deleted_episode_ids"] == [B1.id]`, and B1 is `_GONE`. |
| T6 | `test_a_memory_without_the_live_read_fails_closed` (D4) | A local fake `_ListOnlyMemory` with `list_episodes(*, limit=None)` returning one episode, `dataclasses.replace(_episode(5), id="ep-listed", agent_ids=["agent-b"])`, `get_by_ids` returning `[]`, and `evict_by_ids` recording its ids. No `iter_live_episodes` and no archive. The premise: `[e.id for e in await memory.list_episodes()] == ["ep-listed"]`. | `ErasureManager(memory, None, None).forget_agent_memory("agent-b")` raises `ErasureCascadeIncomplete`. `isinstance(enumeration_error, AttributeError)`, with `"iter_live_episodes"` in its text. `deleted_episode_ids == []`. `memory.evicted == []`: there is no fallback. |
| T7 | `test_no_memory_wired_keeps_the_empty_result` (F-130 unchanged) | `ErasureManager(episodic_memory=None, attachment_store=None, audit_log=None)`. | `forget_agent_memory("agent-b")` and `forget_resource("/x")` each return an `ErasureResult` with `count == 0` and `deleted_episode_ids == []`, without raising. |
| T8 | `test_when_both_scans_fail_the_live_error_is_raised_and_both_are_logged` | Make a directory at `tmp_path / "chroma" / ARCHIVE_FILENAME` (S1 R13's blocker). In the rig, `em.archive_available is False`. Store B1 (`STORED`); `_raw(em, [B1.id])["ids"] == [B1.id]`. `caplog.set_level(logging.ERROR)`. | Install the fault. `forget_agent_memory("agent-b")` raises `ErasureCascadeIncomplete`. `str(enumeration_error) == "injected: the live scan read failed"`. `failures == {}`. `deleted_episode_ids == []`. `_errors(caplog)` holds a message containing `"the live erasure scan failed"`, followed by one containing `"the archive erasure scan failed"`. B1 is still live (`_raw`). |

12 new tests. Boundaries covered:
- **Happy path:** T4, R2.
- **Errors:** R1, R3, R4, T1, T2, T3, T6, T8.
- **Empty or None:** T7, and R2's page arithmetic.
- **The seam:** T5, through the route to the store.

## Focused gate (`-n 0 -p no:randomly`; confirm `probos.__file__` resolves inside this worktree's `src`)

```text
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf905_erasure_live_scan.py tests/test_erasure_manager.py tests/test_bf868_erasure_declared_fields.py tests/test_bf869_fused_frame_refs.py tests/test_ad1340_s1_erasure.py tests/test_ad1340_s1_eviction.py tests/test_ad1340_s1_archive_store.py tests/test_ad1340_s1_restore_reset.py tests/test_ad1340_s2a_archive_lookup.py tests/test_ad1340_s2a_lookup_route.py tests/test_bf902_fts_reconciliation.py tests/test_ad1293_turn_record_reaches_episode.py tests/test_ad689_edge_backfill.py -q -n 0 -p no:randomly
d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check
```

Consumer tests of the changed files, enumerated in Absence Verified 4 and 8:
- **`knowledge/erasure.py`:** every test file that imports it: `test_erasure_manager.py`, `test_bf868_erasure_declared_fields.py`, `test_bf869_fused_frame_refs.py`, `test_ad1340_s1_erasure.py`, and `test_ad1340_s2a_lookup_route.py` (through `routers/security.py`).
- **`episodic.py`:** the six `test_ad1340_s*` files, `test_bf902_fts_reconciliation.py`, `test_ad1293_turn_record_reaches_episode.py` (changed), and `test_ad689_edge_backfill.py` (the AD-689 consumer).

The many other `test_episodic*` and recall tests are left to the broad gate, because no existing line of `episodic.py` changes. The broad gate runs once, by the orchestrator: `scripts/run_test_gate.py --label bf-905 --receipt logs/gates/bf-905.receipt.json`.

## Milestone and cut point (at most about 150 Builder tool calls)

| Milestone | Sections | Estimate | Cut if past about 150 calls |
|---|---|---|---|
| M1 | 1 to 5, then Tracking | 70 to 100 | Stop after Sections 1 to 4, with the focused gate green on the existing files (commit). Section 5 and Tracking become M1b. |

Commit by explicit path (`git add <path>`; never `git add -A`). Run `git diff --cached --stat` and stop on any unexpected file with more than 200 deletions. `PROGRESS.md` and `DECISIONS.md` may hold unrelated work by the Captain: stage only the hunks this contract names. `config/system.yaml` is not touched.

## Diff Reviewer properties (verify each; erasure integrity and privacy; GPT-6.1 Sol, cross-family, required)

1. **No false success.** No path through `forget_resource` or `forget_agent_memory` returns an `ErasureResult` when a live match was not enumerated. The four cases are: the live read raised, there was no collection, a live row did not rebuild, or the memory has no `iter_live_episodes`. Each ends in `ErasureCascadeIncomplete` with `enumeration_error` set.
2. **The scans are independent.** A live-scan failure never skips the archive scan, and the reverse. The two `_scan` calls are unconditional and sequential, and neither reads the other's result.
3. **Erase, then raise once.** Every id found by either scan reaches `_forget_all` before the single raise. `enumeration_error` is the live error when both scans fail, and each failure is logged at ERROR.
4. **The happy path is unchanged.** `deleted_episode_ids` is the same, and every store is at zero: T4, S1 `test_cascades_reach_the_archive`, and the BF-868 cascade tests.
5. **AD-689 is untouched.** `list_episodes` is byte-identical, `knowledge/backfill.py` is unchanged, and `test_ad689_edge_backfill.py` passes.
6. **Nothing else moves.** There is no change to:
   - the archive side: `iter_archived_episodes`, `episode_archive.py`, or `_archived_episodes`'s guard and yield lines;
   - locking (no lock is taken or changed);
   - `forget_episode`, `_forget_all` or the `/forget` route.
7. **No content in logs.** The new WARNING carries an id and an exception type name only, with no `exc_info`. No document or metadata value is logged.
8. **Not a recall surface.** The only caller of `iter_live_episodes` in `src/` is `knowledge/erasure.py`, and it has no `hasattr` fallback.
9. **SRP ratchet.** `ErasureManager` has 15 direct methods, and `check_architecture_principles.py --check` exits 0.

**Consumer that must accept the change:** the Captain's HTTP client calling `POST /api/security/forget` with `agent_id` or `resource_path`. On a live-read fault it now gets 500 instead of a 200 that hid an incomplete erasure, and a retry once the fault clears returns 200 with the remaining matches erased (T5).

## Mutation table (campaign of record: run once by the orchestrator on the frozen candidate; record the base tree and the sha256 of `episodic.py`, `erasure.py` and `tests/test_bf905_erasure_live_scan.py` in the BF-905 DECISIONS entry; a Builder whose three files match does not repeat it)

Every SEARCH is the stripped, whole, post-build line, including any trailing comment, with exactly one match in the named file. Count it first: zero or more than one match is INERT, not killed. Run the unmodified baseline first, mutate in place with a `.mutbak` sibling, restore in `finally`, and treat a timeout as INVALID. Run each row against the test file that holds its killer.

| ID | File | SEARCH | REPLACE | Killed by |
|---|---|---|---|---|
| L1 | `src/probos/cognitive/episodic.py` | `raise EpisodeErasureIncomplete("erasure_live_store_unavailable")  # BF-905: a stopped store is never an empty scan` | `return` | R1, T3 |
| L2 | `src/probos/cognitive/episodic.py` | `raise EpisodeErasureIncomplete(f"erasure_live_rows_unrehydratable:{unreadable_rows}")` | `return` | T2 |
| L3 | `src/probos/cognitive/episodic.py` | `unreadable_rows += 1` | `pass` | T2 |
| L4 | `src/probos/cognitive/episodic.py` | `for start in range(0, len(ids), page_size):` | `for start in range(0, min(len(ids), page_size), page_size):` | R2 |
| L5 | `src/probos/cognitive/episodic.py` | `ids = list(collection.get(include=[])["ids"] or [])` | `ids = []` | R2, T4 |
| L6 | `src/probos/cognitive/episodic.py` | `logger.warning("BF-905: live episode %s could not be rehydrated (%s); erasure cascades cannot match it", episode_id, type(exc).__name__)` | `logger.debug("BF-905: live episode %s could not be rehydrated (%s); erasure cascades cannot match it", episode_id, type(exc).__name__)` | T2 |
| L7 | `src/probos/cognitive/episodic.py` | `logger.warning("BF-905: live episode %s could not be rehydrated (%s); erasure cascades cannot match it", episode_id, type(exc).__name__)` | `logger.warning("BF-905: live episode %s could not be rehydrated (%s); erasure cascades cannot match it", episode_id, type(exc).__name__, exc_info=True)` | T2 |
| E1 | `src/probos/knowledge/erasure.py` | `archived, archive_error = await self._scan("archive", self._archived_episodes(), matches)` | `archived, archive_error = ([], None) if live_error is not None else await self._scan("archive", self._archived_episodes(), matches)` | T1, T5 |
| E2 | `src/probos/knowledge/erasure.py` | `enumeration_error = live_error if live_error is not None else archive_error` | `enumeration_error = archive_error` | T1, T2, T3, T6 |
| E3 | `src/probos/knowledge/erasure.py` | `enumeration_error = live_error if live_error is not None else archive_error` | `enumeration_error = archive_error if archive_error is not None else live_error` | T8 |
| E4 | `src/probos/knowledge/erasure.py` | `return found, exc  # BF-905: the matches found before the failure are still erased` | `return found, None` | T1, T2, T3, T6 |
| E5 | `src/probos/knowledge/erasure.py` | `async for episode in memory.iter_live_episodes():` | `for episode in await memory.list_episodes(limit=None):` | T1, T3, T6 |

E1 is the issue's "merge them back" mutant: a live failure skips the archive scan, which is what the single `try` did. E5 is the `list_episodes` fallback.

**S1 rows (`prompts/ad-1340-s1-archive-and-erase.md:1412-1440`) re-run in the same campaign**, because `erasure.py` changed:
- **Unchanged lines:** every S1 row whose file is `knowledge/erasure.py` except K7 and V1 anchors on a line BF-905 keeps byte for byte: K1, K2, K3, K5, K6, K8, K9 and K10. Each must still be KILLED by its S1 killer.
- **K7 is retired.** Its line (`enumeration_error = exc  # the archive scan failed: ...`) no longer exists; E4 replaces it.
- **V1 re-anchors its REPLACE** (the SEARCH, the yield line in `_archived_episodes`, is unchanged): `if str(getattr(episode, "id", "")) not in {str(getattr(e, "id", "")) async for e in _live_episodes(self._episodic_memory)}: yield episode`. It must be killed by S1 R24 (`test_cascade_matches_an_archived_version_shadowed_by_a_live_one`, `tests/test_ad1340_s1_erasure.py:873`).

## What this does NOT change

- `list_episodes` (`episodic.py:2216-2247`) and its AD-689 consumer `knowledge/backfill.py:271`.
- `iter_archived_episodes`, `episode_archive.py`, and every archive-side behaviour (they already fail closed).
- Any lock: no store write lock is taken by the scan, as `list_episodes` took none. Lock order is S2b's prerequisite (a).
- `forget_episode` (by id; it does not scan), `_forget_all`, `_attachment_ids_for_episode`, and #1523 F-129 and F-130.
- `routers/security.py` (D6) and the route's missing authorization, which is already known (#1568 discussion) and not this BF's.
- S2a's F-140 (S2b owns it), `cognitive/episodic_mock.py` (D4), `config/system.yaml`, `config.py` and `startup/`.

## Tracking (M1, last)

- **`PROGRESS.md`:** a top entry in BF-902's style: `**BF-905 (2026-10-18), #1587 -- the erasure cascades' live scan fails closed: ...**`, naming the new reader, the two scans, the 500 through `/forget`, and the test count.
- **`DECISIONS.md`:** a `### BF-905 -- The erasure cascades' live scan fails closed` entry beside BF-902's (`DECISIONS.md:54`). It holds D2 to D7 in one line each and the campaign of record (base tree, the three sha256s, each row's result and killer, and the S1 re-runs).
- **Ledger:** run `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py`, then `--check` and `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1184_ad_ledger.py -q -n 0`. The ledger reads BF numbers (`scripts/gen_ad_ledger.py:210`).
- **`docs/development/roadmap.md`:** no row. Its Bug Tracker table lists only open BFs filed and deliberately not fixed (`roadmap.md:1139-1142`).

## Acceptance criteria

1. Sections 1 to 5 applied verbatim. Each SEARCH occurs exactly once before it is applied, and every listed file is changed exactly as shown.
2. All 12 new tests pass, and the focused gate and `check_architecture_principles.py --check` are green.
3. Issue acceptance 1 to 5 are met by R1 to R4 and T1 to T8: (i) T1, (ii) T2, (iii) T3, (iv) T4, (v) T5.
4. Every row L1 to L7 and E1 to E5 is KILLED, and the S1 re-runs are KILLED (K7 retired, V1 re-anchored), in one campaign of record recorded in `DECISIONS.md`. No row is INERT or INVALID.
5. The GPT-6.1 Sol Diff Reviewer (cross-family) has reviewed the diff against the nine properties above.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Prior Art and Blind Spots (2026-10-18)

- **Internal prior art, absorbed.** The archive half of the same scan: `iter_archived_episodes` (`episodic.py:2870-2894`) and S1's R13 (`tests/test_ad1340_s1_erasure.py:608`). BF-905 is its live twin, with the same "scan past, then raise a count" shape and the same `page_size=500`.
- **Internal prior art, rejected.** `_iter_collection_pages` (`episodic.py:353`): its own offset-stability precondition (`:377-383`) rules it out for a store that changes during the scan (D3).
- **External prior art: skipped.** This is ProbOS-specific plumbing between two internal stores, with no outside analogue that would change the design. `docs/research/reference-projects.md` was not consulted for that reason.
- **Blind spot: rows that change during the scan.** A row stored after the id read is not seen (as today). A row archived during the scan is seen by the archive scan, which runs after the live one. A row deleted during the scan is gone (D3).
- **Blind spot: a partly consumed generator.** If the predicate raises, `_scan` stops iterating without closing the generator, and asyncio finalizes it later. That was also true of S1's single generator. Considered and deferred: wrapping the scan in `contextlib.aclosing` would be a hygiene change, not a correctness one.
- **Blind spot: the archive guard.** The `hasattr(..., "iter_archived_episodes")` guard in `_archived_episodes` still lets a memory without an archive read skip the archive silently. It is kept, under the issue's "no archive-side changes" and because K2 anchors on it. The only production memory, `EpisodicMemory`, defines the method. Considered and deferred.
- **Blind spot: no content in logs.** The new per-row WARNING omits the traceback (D7).

## Verified Against Codebase (2026-10-18, tree `01acb85c`)

```text
git log --oneline -1                         -> 01acb85c Merge origin/main into feat/ad1340-s2a-20261018-76c95074
git diff --stat 28a3786b 01acb85c -- src/probos/knowledge/erasure.py src/probos/cognitive/episodic.py src/probos/routers/security.py tests/test_erasure_manager.py tests/test_bf868_erasure_declared_fields.py tests/test_bf869_fused_frame_refs.py
  -> episodic.py | 133, routers/security.py | 141 (erasure.py and the three test files unchanged)

rg -n "async def list_episodes|async def iter_archived_episodes|def _metadata_to_episode|erasure_live_store_unavailable|async def stop|self\._collection = None|_archive_state = \"absent\"|async def get_by_ids" src/probos/cognitive/episodic.py
  2216: async def list_episodes(self, *, limit: int | None = None) -> list[Episode]:
  2249: async def get_by_ids(
  2789: raise EpisodeErasureIncomplete("erasure_live_store_unavailable")  # stopped or never started
  2870: async def iter_archived_episodes(self, *, page_size: int = 500) -> AsyncIterator[Episode]:
  4293: def _metadata_to_episode(
  1662: async def stop(self) -> None:   1663/1691: self._collection = None   1685: self._archive_state = "absent"
Read episodic.py:2216-2247 (list_episodes: 2224-2225 no collection -> [], 2226-2230 get failure -> [] at DEBUG, 2237 sort, 2241-2246 skip at DEBUG)
Read episodic.py:2870-2894 (iter_archived_episodes: catches Exception per record 2885, raises EpisodeArchiveIntegrityError 2894)
Read episodic.py:4293-4387 (_metadata_to_episode: 4298 AnchorFrame(**json.loads(...)); 4360-4367 unguarded json.loads)
Read episodic.py:353-401 (_iter_collection_pages; precondition 377-383)
rg -n "AsyncIterator|EpisodeErasureIncomplete|^    Episode," src/probos/cognitive/episodic.py   -> 19 (import), 38 (import), 48 (import)
rg -n "self\._collection(: [^=]+)? = None|def archive_available" src/probos/cognitive/episodic.py   -> 1384: self._collection: Any = None ; 1537
rg -n "AD-689: failed to reconstruct episode" src/probos/cognitive/episodic.py   -> 2245 only (1a SEARCH is unique)
rg -n "include=\[\]" src/probos   -> __main__.py:2261 em._collection.get(include=[]) ; episodic.py:1739, 2954, 3068
rg -n "class EpisodeErasureIncomplete|async def iter_records|page_size < 1|episode_archive_page_size_invalid" src/probos/cognitive/episode_archive.py   -> 145, 601, 608, 609
rg -n "class AnchorFrame" -B2 src/probos/types.py   -> 488 @dataclass(frozen=True) / 489 class AnchorFrame

Read src/probos/knowledge/erasure.py (whole, 402 lines): imports AsyncIterator, Callable (9); ErasureCascadeIncomplete 68-84; ErasureManager 87;
  methods at 88, 98, 128, 142, 154, 175, 207, 212, 228, 274, 284, 337, 372, 392, 400 (15); _matching_ids 154-173; _forget_all 175-205 (raise 202-204);
  _list_episodes 207-210; _candidate_episodes 212-226
rg -n "SRP_MAX_DIRECT_METHODS|SRP_MAX_BODY_LINES" scripts/check_architecture_principles.py   -> 187: = 500 ; 188: = 15 ; 568: if methods > SRP_MAX_DIRECT_METHODS:

rg -n "ErasureCascadeIncomplete|forget|ErasureManager" src/probos/routers/security.py   -> 22 import ErasureManager ; 73 @router.post("/forget") ; 79 ErasureManager( ; 86/88/90 forget_* calls
rg -n "exception_handler\(" src/probos/api.py   -> 165 (IntentAuthorizationDenied only)
rg -n "middleware\(|FastAPI\(|debug=" src/probos/api.py   -> 145 FastAPI(title=..., lifespan=_lifespan) ; 184 add_middleware(CORSMiddleware ...)
rg -n "raise_app_exceptions" .venv/Lib/site-packages/httpx/_transports/asgi.py   -> 90: raise_app_exceptions: bool = True
rg -n "def (update|get)\b" .venv/Lib/site-packages/chromadb/api/models/Collection.py   -> 129 get(ids=..., include=...) ; 441 update(ids, embeddings, metadatas, documents, ...)

rg -n "^def _episode|^def _ids|^async def _memory|^def _raw|^class _CollectionProxy|^def _record_collection" tests/test_ad1340_s1_eviction.py   -> 62, 75, 88, 121, 174, 197
Read tests/test_ad1340_s1_erasure.py:36-235   -> _LIVE_TRACES 72, _ARCHIVED_TRACES 76, _GONE 80, _manager 116, _traces 146, _seed 174
rg -n "test_cascade_erases_the_live_matches_when_the_archive_scan_fails|test_cascade_matches_an_archived_version_shadowed" tests/test_ad1340_s1_erasure.py   -> 608, 873
rg -n "_FORGET|def _runtime|def _client|_data_dir" tests/test_ad1340_s2a_lookup_route.py   -> 45, 200, 209, 214
rg -n "list_episodes" tests/test_erasure_manager.py tests/test_bf868_erasure_declared_fields.py tests/test_bf869_fused_frame_refs.py
  -> test_erasure_manager.py:41, :132 ; test_bf868_erasure_declared_fields.py:63 ; test_bf869_fused_frame_refs.py:47
rg -n "from __future__|^import|^from" (heads of the three fake files)   -> __future__ at 3 / 30 / 22; the 3a, 3d, 3f SEARCH blocks are their import heads
Read tests/test_ad1293_turn_record_reaches_episode.py:782-789   -> the Section 4 SEARCH, verbatim
rg -n "asyncio_mode|requires-python" pyproject.toml   -> 181 asyncio_mode = "auto" ; 9 requires-python = ">=3.12" (zip strict=True is available)
rg -n "K2|K7|V1" prompts/ad-1340-s1-archive-and-erase.md   -> 1413 (K2), 1418 (K7), 1437 (V1)
```

**Anchors moved since the issue (`28a3786b` to `01acb85c`):**

| Issue anchor | Now |
|---|---|
| `list_episodes` `episodic.py:2128-2159` | `:2216-2247` |
| `:2136-2137` (no collection) | `:2224-2225` |
| `:2139-2142` (get failure) | `:2226-2230` |
| `:2149` (sort) | `:2237` |
| `:2153-2158` (skip) | `:2241-2246` |
| `_metadata_to_episode` `:4177`, `:4239-4246` | `:4298`, `:4360-4367` |
| `iter_archived_episodes` `:2782-2806` | `:2870-2894` |
| `stop()` `:1644`, `:1666` | `:1663` (and `:1691`), `:1685` |
| `erasure.py` `:154-173`, `:172`, `:175-205`, `:202-204`, `:207-210`, `:212-226` | unchanged |

## Absence Verified (2026-10-18)

1. **CLAIM:** nothing named BF-905 or `iter_live_episodes` exists yet.
   - **RUN:** `rg -l "BF-905|iter_live_episodes|erasure_live_rows_unrehydratable" .` over the whole tree.
   - **FOUND:** none.
   - **HOLDS:** yes.
2. **CLAIM:** `list_episodes` has exactly two production callers.
   - **RUN:** `rg -n "list_episodes" --glob "*.py"`.
   - **FOUND in `src/`:** `knowledge/backfill.py:271`, `:273`; `knowledge/erasure.py:207`, `:208`, `:210`, `:221`; `cognitive/episodic.py:2216`, `:2229` (definition and its log).
   - **HOLDS:** yes. After BF-905, erasure no longer calls it.
3. **CLAIM:** `MockEpisodicMemory` is not an erasure consumer.
   - **RUN:** `rg -n "MockEpisodicMemory|episodic_mock" src/` and `rg -n "async def |    def " src/probos/cognitive/episodic_mock.py`.
   - **FOUND:** only its definition (`episodic_mock.py:37`). Its methods are `__init__`, `is_available`, `start`, `stop`, `set_activation_tracker`, `set_participant_index`, `set_erasure_sidecar_paths`, `embedding_migration_required`, `should_store`, `seed`, `_get_store_write_lock`, `store`, `recall`, `recall_for_agent`, `recent_for_agent`, `count_for_agent`, `recall_by_intent`, `recent` and `get_stats`: no `list_episodes`, `get_by_ids` or `evict_by_ids`.
   - **ALSO RUN:** `rg -n "ErasureManager\(" src/`.
   - **ALSO FOUND:** `routers/security.py:79` only.
   - **HOLDS:** yes.
4. **CLAIM:** no source-text test pins a line BF-905 changes in `erasure.py`.
   - **RUN:** `rg -n "_candidate_episodes|_list_episodes|_matching_ids|erasure\.py[\"']|knowledge/erasure" tests/`.
   - **FOUND:**
     - `test_ad1293_turn_record_reaches_episode.py:783-784`, a docstring that Section 4 updates;
     - `test_ad1340_s1_erasure.py:63`, a file name in `_ERASE_CALLERS` (R10 counts `EvictionDisposition.ERASE` references; none change);
     - `test_ad1326_challenger_e2e.py:258`, an unrelated local helper.
   - **HOLDS:** yes.
5. **CLAIM:** nothing maps `ErasureCascadeIncomplete` to a response, so `/forget` answers 500.
   - **RUN:** `rg -n "exception_handler\(" src/probos/api.py`, `rg -n "middleware\(|FastAPI\(" src/probos/api.py` and `rg -n "ErasureCascadeIncomplete" src/probos/routers/security.py`.
   - **FOUND:** the handler at `api.py:165` (for `IntentAuthorizationDenied` only), `api.py:145`, `api.py:184` (CORS), and nothing in `security.py`.
   - **HOLDS:** yes.
6. **CLAIM:** no script, config, doc or workflow references the reads being changed.
   - **RUN:** `rg -l "iter_archived_episodes|list_episodes"` over `scripts/`, `config/`, `docs/` and `.github/`.
   - **FOUND:** none.
   - **HOLDS:** yes.
7. **CLAIM:** `ErasureManager` has 15 direct methods today.
   - **RUN:** a full read of `erasure.py`, counting every `def` and `async def` at class-body indentation.
   - **FOUND:** 15 (listed in Verified).
   - **HOLDS:** yes. After BF-905 it is 15 − 2 + 2 = 15.
8. **CLAIM:** the three fakes are the only erasure fakes that define `list_episodes`.
   - **RUN:** `rg -n "list_episodes" tests/`.
   - **FOUND:** fakes at `test_erasure_manager.py:41`, `test_bf868_erasure_declared_fields.py:63` and `test_bf869_fused_frame_refs.py:47`. `test_ad689_edge_backfill.py:166`, `:263` assign `list_episodes` on a backfill mock, not an erasure one. The other hits call a real memory.
   - **HOLDS:** yes.
9. **CLAIM:** `/forget`'s missing authorization is already recorded.
   - **RUN:** `gh issue view 1568 --comments | grep -n -i -E "/forget.{0,60}(auth|token|crew_scope|unauth)"`.
   - **FOUND:** line 176: "`/api/security/forget` has no authorization dependency and the app has no auth middleware (CORS only)".
   - **HOLDS:** yes. It is not this BF's.

## Not verified

- That `get(include=[])` without `ids` returns every id on the installed ChromaDB. It rests on the existing call at `__main__.py:2261`, and R2 confirms it at build time.
- That `Collection.update` with metadata alone leaves the stored document and embedding as they were. T2 asserts the row is still live before relying on it.
