"""AD-1346 M3b (#1604): the shadow admission recorder, a synchronous ``offer`` and a write-behind flusher.

``AdmissionService.shadow``, in a service built with a recorder, hands it each verdict it counted
and the ``decide`` time it measured. ``offer`` adds them to in-memory counts and returns: it awaits
nothing and does no I/O. The flusher, an asyncio task this object holds from ``start``, hands
those counts to ``AdmissionShadowStore.write_batch`` every ``FLUSH_INTERVAL_SECONDS``. It calls
``prune`` at each flush whose UTC day of the injected wall clock differs from the day of the last
prune that succeeded. ``start`` marks the hour it
ran, so the first write of a boot that succeeds adds that boot's marker row even when nothing was
offered.

The producer marker is ``offered``, counted by ``offer``; the consumer marker is ``written``, the
verdicts a committed ``write_batch`` added to the aggregates. Both reach the store per (boot, hour)
in the transaction of the counts they describe. Bounds (D10): a would-refuse sample beyond
``SAMPLE_BUFFER_LIMIT`` pending samples is not kept and is counted as ``samples_dropped``; a verdict
that needs a new pending key beyond ``PENDING_KEY_LIMIT`` is neither counted in the aggregates nor
sampled, and is counted as ``dropped``; a verdict offered once ``stop`` began is counted in memory
as ``late`` and is not written.

AD-1346 M3c: ``offer`` takes the site's own outcome (``today_outcome``). A verdict it aggregates
with one is also counted for parity, and kept as a disagreement sample when ``is_disagreement``
holds; beyond ``DISAGREEMENT_BUFFER_LIMIT`` pending ones it is counted in memory as
``disagreement_samples_dropped``. A pending parity key always has a pending aggregate key with the
same hour, work kind, seam, outcome and reason code: both are counted by the same call and are
detached, written and put back together. So, for the two values of ``TODAY_OUTCOMES`` (the only ones
``AdmissionService.shadow`` passes), the parity keys pending are at most twice the aggregate keys
pending (register R10 says when those exceed ``PENDING_KEY_LIMIT``). A flush that raises an
``Exception`` leaves the flusher running and is counted in memory as ``flush_errors`` (R1); a
``BaseException`` that is not an ``Exception`` ends it.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Final

from probos.admission.store import (
    DAY_SECONDS,
    DISAGREEMENT_RING_SIZE,
    SAMPLE_RING_SIZE,
    AdmissionShadowStore,
    ShadowBatch,
    ShadowDisagreement,
    ShadowSample,
    utc_hour,
)
from probos.admission.taxonomy import LATENCY_BUCKETS, OUTCOME_ADMIT, OUTCOME_WOULD_REFUSE, TODAY_REFUSE

if TYPE_CHECKING:
    from collections.abc import Callable

    from probos.admission.record import AdmissionVerdict

logger = logging.getLogger(__name__)

#: D45: seconds between two flushes while the recorder runs.
FLUSH_INTERVAL_SECONDS: Final = 5.0
#: D44: pending would-refuse samples kept between two writes that succeed (the store's ring size).
SAMPLE_BUFFER_LIMIT: Final = SAMPLE_RING_SIZE
#: D44: ``offer`` adds no new pending aggregate key while this many are pending. A failed write's
#: aggregate counts are added back with no limit, so the pending keys can exceed this after a failed
#: write (register R10, #1604).
PENDING_KEY_LIMIT: Final = 50_000
#: D45: after the flusher ends, ``stop`` flushes while anything is pending, at most this many times.
STOP_FLUSH_ATTEMPTS: Final = 2
FLUSHER_TASK_NAME: Final = "ad1346-shadow-flusher"
#: AD-1346 M3c (D58): pending disagreement samples kept between two writes that succeed (the store's ring size).
DISAGREEMENT_BUFFER_LIMIT: Final = DISAGREEMENT_RING_SIZE
#: The totals ``counters`` returns, in order. Append-only; AD-1346 M3c appended the last two.
COUNTER_NAMES: Final[tuple[str, ...]] = (
    "offered", "written", "dropped", "samples_dropped", "late", "flush_failures", "disagreement_samples_dropped",
    "flush_errors",
)
_HOUR_SECONDS: Final = 3_600


def _add(target: dict[Any, int], source: dict[Any, int]) -> None:
    for key, count in source.items():
        target[key] = target.get(key, 0) + count


def is_disagreement(outcome: str, today_outcome: str) -> bool:
    """AD-1346 M3c (D58): the shadow outcome and the site's own differ: a would-refuse where the site admitted, or an admit where it refused."""
    return (outcome == OUTCOME_WOULD_REFUSE) != (today_outcome == TODAY_REFUSE)


class ShadowRecorder:
    """Ship's Computer service: counts shadow verdicts in memory and writes them behind (AD-1346 M3b)."""

    def __init__(self, store: AdmissionShadowStore, *, wall_clock: Callable[[], float] = time.time) -> None:
        if not isinstance(store, AdmissionShadowStore):
            raise TypeError("ShadowRecorder needs the AdmissionShadowStore")
        self._store = store
        self._wall_clock = wall_clock
        self._boot_id = uuid.uuid4().hex
        self._hour_index = -1
        self._hour = ""
        self._aggregates: dict[tuple[str, str, str, str, str, int], int] = {}
        self._samples: list[ShadowSample] = []
        self._parity: dict[tuple[str, str, str, str, str, str], int] = {}
        self._disagreements: list[ShadowDisagreement] = []
        self._offered: dict[str, int] = {}
        self._dropped: dict[str, int] = {}
        self._samples_dropped: dict[str, int] = {}
        self._totals: dict[str, int] = dict.fromkeys(COUNTER_NAMES, 0)
        self._pruned_day = -1
        self._stopping = False
        self._stop_requested = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def boot_id(self) -> str:
        """This recorder's boot id in the marker rows: a fresh ``uuid4`` hex per recorder."""
        return self._boot_id

    def offer(self, verdict: AdmissionVerdict, elapsed_ns: int, today_outcome: str | None = None) -> None:
        """Count one verdict in memory and, within the bounds below, aggregate it with its ``decide`` time and sample it when it is not an admit.

        A verdict that needs a new pending key beyond ``PENDING_KEY_LIMIT`` is counted as dropped and
        is neither aggregated nor sampled; a sample beyond ``SAMPLE_BUFFER_LIMIT`` pending samples is
        not kept and is counted as samples_dropped. AD-1346 M3c: a verdict it aggregates with a
        ``today_outcome`` is also counted for parity, and kept as a disagreement sample when
        ``is_disagreement`` holds, within ``DISAGREEMENT_BUFFER_LIMIT`` (beyond it, counted as
        disagreement_samples_dropped). Once ``stop`` began, it counts the verdict as late and keeps
        nothing. It awaits nothing and does no I/O.
        """
        if self._stopping:
            self._totals["late"] += 1
            return
        now = self._wall_clock()
        hour = self._hour_of(now)
        self._totals["offered"] += 1
        self._offered[hour] = self._offered.get(hour, 0) + 1
        bucket = min(elapsed_ns.bit_length(), LATENCY_BUCKETS - 1)
        key = (hour, verdict.work_kind, verdict.seam, verdict.outcome, verdict.reason_code, bucket)
        if key in self._aggregates:
            self._aggregates[key] += 1
        elif len(self._aggregates) < PENDING_KEY_LIMIT:
            self._aggregates[key] = 1
        else:
            self._totals["dropped"] += 1
            self._dropped[hour] = self._dropped.get(hour, 0) + 1
            return
        if today_outcome is not None:
            parity = (hour, verdict.work_kind, verdict.seam, today_outcome, verdict.outcome, verdict.reason_code)
            self._parity[parity] = self._parity.get(parity, 0) + 1
            if is_disagreement(verdict.outcome, today_outcome):
                if len(self._disagreements) < DISAGREEMENT_BUFFER_LIMIT:
                    self._disagreements.append(ShadowDisagreement(hour, now, verdict, elapsed_ns, today_outcome))
                else:
                    self._totals["disagreement_samples_dropped"] += 1
        if verdict.outcome == OUTCOME_ADMIT:
            return
        if len(self._samples) < SAMPLE_BUFFER_LIMIT:
            self._samples.append(ShadowSample(hour, now, verdict, elapsed_ns))
        else:
            self._totals["samples_dropped"] += 1
            self._samples_dropped[hour] = self._samples_dropped.get(hour, 0) + 1

    def _hour_of(self, now: float) -> str:
        index = int(now // _HOUR_SECONDS)
        if index != self._hour_index:
            self._hour_index = index
            self._hour = utc_hour(index * _HOUR_SECONDS)
        return self._hour

    def start(self) -> None:
        """Mark the current hour for this boot's marker row and start the flusher task.

        Raises ``RuntimeError`` when it has already started or ``stop`` began.
        """
        if self._task is not None or self._stopping:
            raise RuntimeError("AD-1346 M3b: a shadow recorder starts once")
        hour = self._hour_of(self._wall_clock())
        self._offered.setdefault(hour, 0)
        self._task = asyncio.create_task(self._run(), name=FLUSHER_TASK_NAME)

    async def _run(self) -> None:
        while not self._stop_requested.is_set():
            try:
                await asyncio.wait_for(self._stop_requested.wait(), FLUSH_INTERVAL_SECONDS)
            except TimeoutError:
                pass
            try:
                await self._flush()
            except Exception:  # noqa: BLE001 -- R1 (#1604, D59): the flusher outlives a flush that raised
                # A log call in _flush that raised (F-212's class) runs after any batch it detached was put
                # back (_restore precedes _failed); the next tick flushes again. Counted, not logged,
                # because the log call may be what raised.
                self._totals["flush_errors"] += 1

    async def stop(self) -> None:
        """Refuse later offers, let the flusher end after its last flush, then flush what is still pending.

        It waits for the flusher without cancelling it, so this call interrupts no write. Then it
        flushes while anything is pending, at most ``STOP_FLUSH_ATTEMPTS`` times, and logs a warning
        naming what was not written. A flush that raises an ``Exception`` is logged by the flush,
        not raised here.
        """
        self._stopping = True
        self._stop_requested.set()
        task = self._task
        if task is not None:
            await asyncio.wait((task,))
            if not task.cancelled() and task.exception() is not None:
                logger.warning("AD-1346 M3b: the shadow flusher ended with an exception", exc_info=task.exception())
        for _ in range(STOP_FLUSH_ATTEMPTS):
            if not self._pending():
                return
            await self._flush()
        if self._pending():
            logger.warning(
                "AD-1346 M3b: %d shadow verdicts and %d samples were not written before the recorder stopped",
                sum(self._aggregates.values()), len(self._samples),
            )

    async def _flush(self) -> None:
        now = self._wall_clock()
        day = int(now // DAY_SECONDS)
        if day != self._pruned_day:
            try:
                pruned = await self._store.prune(now)
            except Exception:
                self._failed("prune")
            else:
                self._pruned_day = day
                if pruned != (0, 0):
                    logger.info("AD-1346 M3b: the shadow store pruned %d aggregate and %d marker rows", *pruned)
        if not self._pending():
            return
        batch = ShadowBatch(
            self._aggregates, self._samples, self._offered, self._dropped, self._samples_dropped,
            parity=self._parity, disagreements=self._disagreements,
        )
        self._aggregates, self._samples, self._offered, self._dropped, self._samples_dropped = {}, [], {}, {}, {}
        self._parity, self._disagreements = {}, []
        try:
            written = await self._store.write_batch(self._boot_id, batch)
        except BaseException as exc:
            self._restore(batch)
            if not isinstance(exc, Exception):
                raise
            self._failed("write")
            return
        self._totals["written"] += written

    def _restore(self, batch: ShadowBatch) -> None:
        """Add a batch that was not written back to what is pending, keeping at most ``SAMPLE_BUFFER_LIMIT`` samples and ``DISAGREEMENT_BUFFER_LIMIT`` disagreements."""
        _add(self._aggregates, batch.aggregates)
        _add(self._offered, batch.offered)
        _add(self._dropped, batch.dropped)
        _add(self._samples_dropped, batch.samples_dropped)
        kept = batch.samples + self._samples
        for sample in kept[SAMPLE_BUFFER_LIMIT:]:
            self._totals["samples_dropped"] += 1
            self._samples_dropped[sample.hour] = self._samples_dropped.get(sample.hour, 0) + 1
        self._samples = kept[:SAMPLE_BUFFER_LIMIT]
        _add(self._parity, batch.parity)
        disagreements = batch.disagreements + self._disagreements
        self._totals["disagreement_samples_dropped"] += max(0, len(disagreements) - DISAGREEMENT_BUFFER_LIMIT)
        self._disagreements = disagreements[:DISAGREEMENT_BUFFER_LIMIT]

    def _pending(self) -> bool:
        return bool(
            self._aggregates or self._samples or self._offered or self._dropped or self._samples_dropped
            or self._parity or self._disagreements
        )

    def _failed(self, step: str) -> None:
        self._totals["flush_failures"] += 1
        failures = self._totals["flush_failures"]
        logger.log(
            logging.WARNING if failures == 1 else logging.DEBUG,
            "AD-1346 M3b: the shadow store's %s raised (%d failures so far); a batch that was not written stays pending",
            step,
            failures,
            exc_info=True,
        )

    def counters(self) -> dict[str, int]:
        """``COUNTER_NAMES`` and their totals since this recorder was built; a copy."""
        return dict(self._totals)
