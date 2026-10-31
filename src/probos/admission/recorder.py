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
detached, written and put back together. So, for the two values of ``TODAY_OUTCOMES``, the parity
keys pending are at most twice the aggregate keys
pending (register R10 says when those exceed ``PENDING_KEY_LIMIT``). A flush that raises an
``Exception`` leaves the flusher running and is counted in memory as ``flush_errors`` (R1); a
``BaseException`` that is not an ``Exception`` ends it.

AD-1346 M3d3b2: ``offer_ticket`` takes one ``TicketFinding`` that the ticket registry answered for an issue or a sink
check, and whether that check was handed to the service's loop from elsewhere (``off_loop``). Once ``stop`` began it
counts the offer in memory as ``ticket_late`` and checks and keeps nothing. Otherwise, before it counts, it raises
``TypeError`` for a finding that is not an exact ``TicketFinding`` or an ``off_loop`` that is not an exact ``bool``, and
``ValueError`` for a finding whose operation, code or work kind is not an exact ``str`` or whose work kind is neither in
``WORK_KINDS`` nor empty (register R53). It counts an accepted finding by (hour, operation, code, work kind,
``off_loop``) and keeps it as a sample unless its code is ``ticket_issued`` or ``ticket_live``: a ``ticket_missing``
sample within ``TICKET_MISSING_BUFFER_LIMIT`` pending ones, any other within ``TICKET_SAMPLE_BUFFER_LIMIT``. As for
verdicts, a finding that needs a new pending key beyond ``PENDING_KEY_LIMIT`` is counted as ``ticket_dropped`` and not
sampled, and a sample beyond its buffer is counted as ``ticket_samples_dropped``. The work-ticket markers' producer
count is the findings offered and their consumer count the findings a committed write added to ``ticket_findings``;
``start`` marks its hour for a work-ticket marker row too.

A flush writes the work-ticket part in the transaction of the verdicts (D140). When that write raises an ``Exception``
and the part holds a finding count or a sample, the flush writes the batch again at once with each such count and
sample counted as dropped in the work-ticket markers in place of its row (D150), so the second write holds no finding
count and no sample; when that write raises too, the batch is put back whole. Any other batch whose write raised is put
back whole, as before. ``offer`` and ``offer_ticket`` take no lock: each runs on its caller's thread, and the flusher on
the loop that ran ``start``. Totals and pending counts are this recorder's: a new recorder starts from none.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Final

from probos.admission.store import (
    DAY_SECONDS,
    DISAGREEMENT_RING_SIZE,
    SAMPLE_RING_SIZE,
    TICKET_MISSING_RING_SIZE,
    TICKET_SAMPLE_RING_SIZE,
    AdmissionShadowStore,
    ShadowBatch,
    ShadowDisagreement,
    ShadowSample,
    TicketBatch,
    TicketSample,
    utc_hour,
)
from probos.admission.taxonomy import (
    LATENCY_BUCKETS,
    OUTCOME_ADMIT,
    OUTCOME_WOULD_REFUSE,
    TICKET_ISSUED,
    TICKET_LIVE,
    TICKET_MISSING,
    TODAY_REFUSE,
    WORK_KINDS,
)
from probos.admission.tickets import TicketFinding

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
#: AD-1346 M3d3b2 (D151): pending work-ticket samples other than ``ticket_missing`` kept between two writes that
#: succeed (the ``ticket_samples`` ring's size).
TICKET_SAMPLE_BUFFER_LIMIT: Final = TICKET_SAMPLE_RING_SIZE
#: AD-1346 M3d3b2 (D151): pending ``ticket_missing`` samples kept between two writes that succeed (the
#: ``ticket_missing_samples`` ring's size).
TICKET_MISSING_BUFFER_LIMIT: Final = TICKET_MISSING_RING_SIZE
#: The totals ``counters`` returns, in order. Append-only; AD-1346 M3c appended ``disagreement_samples_dropped`` and
#: ``flush_errors``, and AD-1346 M3d3b2 the five ``ticket_`` totals.
COUNTER_NAMES: Final[tuple[str, ...]] = (
    "offered", "written", "dropped", "samples_dropped", "late", "flush_failures", "disagreement_samples_dropped",
    "flush_errors", "ticket_offered", "ticket_written", "ticket_dropped", "ticket_samples_dropped", "ticket_late",
)
_HOUR_SECONDS: Final = 3_600
#: AD-1346 M3d3b2 (D151, register R53): the work kinds ``offer_ticket`` takes: ``WORK_KINDS`` and the empty one that a
#: finding with no registered ticket carries.
_OFFERED_WORK_KINDS: Final = frozenset((*WORK_KINDS, ""))
#: AD-1346 M3d3b2 (D138, D151): the codes ``offer_ticket`` counts and never samples.
_COUNTED_ONLY: Final = frozenset({TICKET_ISSUED, TICKET_LIVE})


def _add(target: dict[Any, int], source: dict[Any, int]) -> None:
    for key, count in source.items():
        target[key] = target.get(key, 0) + count


def is_disagreement(outcome: str, today_outcome: str) -> bool:
    """AD-1346 M3c (D58): the shadow outcome and the site's own differ: a would-refuse where the site admitted, or an admit where it refused."""
    return (outcome == OUTCOME_WOULD_REFUSE) != (today_outcome == TODAY_REFUSE)


def _as_dropped(tickets: TicketBatch) -> TicketBatch:
    """AD-1346 M3d3b2 (D150): ``tickets`` with no finding count and no sample. Its offered counts are kept, its dropped
    counts gain each finding count by hour, and its samples-dropped counts gain one for each sample by hour."""
    dropped = dict(tickets.dropped)
    for (hour, _operation, _code, _work_kind, _off_loop), count in tickets.findings.items():
        dropped[hour] = dropped.get(hour, 0) + count
    samples_dropped = dict(tickets.samples_dropped)
    for sample in tickets.samples + tickets.missing:
        samples_dropped[sample.hour] = samples_dropped.get(sample.hour, 0) + 1
    return TicketBatch(offered=dict(tickets.offered), dropped=dropped, samples_dropped=samples_dropped)


def _first(samples: list[TicketSample], limit: int, dropped: dict[str, int]) -> list[TicketSample]:
    """AD-1346 M3d3b2: the first ``limit`` of ``samples``; each later one is counted in ``dropped`` under its hour."""
    for sample in samples[limit:]:
        dropped[sample.hour] = dropped.get(sample.hour, 0) + 1
    return samples[:limit]


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
        # AD-1346 M3d3b2 (D151): the pending work-ticket part, which _flush detaches as one TicketBatch
        self._ticket_findings: dict[tuple[str, str, str, str, bool], int] = {}
        self._ticket_samples: list[TicketSample] = []
        self._ticket_missing: list[TicketSample] = []
        self._ticket_offered: dict[str, int] = {}
        self._ticket_dropped: dict[str, int] = {}
        self._ticket_samples_dropped: dict[str, int] = {}
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

    def offer_ticket(self, finding: TicketFinding, *, off_loop: bool) -> None:
        """AD-1346 M3d3b2 (D151): count one work-ticket finding in memory and, within the bounds below, keep it as a sample unless its code is ``ticket_issued`` or ``ticket_live``.

        Once ``stop`` began it counts the offer as ticket_late and checks and keeps nothing. Otherwise, before it counts,
        it raises ``TypeError`` for a ``finding`` that is not an exact ``TicketFinding`` or an ``off_loop`` that is not
        an exact ``bool``, and ``ValueError`` for a finding whose operation, code or work kind is not an exact ``str``
        or whose work kind is neither in ``WORK_KINDS`` nor empty (register R53). A finding that needs a new pending
        key beyond ``PENDING_KEY_LIMIT`` is counted as ticket_dropped and is not sampled. A ``ticket_missing`` sample
        beyond ``TICKET_MISSING_BUFFER_LIMIT`` pending ones, or any other beyond ``TICKET_SAMPLE_BUFFER_LIMIT``, is not
        kept and is counted as ticket_samples_dropped. It awaits nothing and does no I/O.
        """
        if self._stopping:
            self._totals["ticket_late"] += 1
            return
        if type(finding) is not TicketFinding or type(off_loop) is not bool:
            raise TypeError("AD-1346 M3d3b2: offer_ticket takes an exact TicketFinding and an exact bool off_loop")
        operation, code, work_kind = finding.operation, finding.code, finding.work_kind
        exact = type(operation) is str and type(code) is str and type(work_kind) is str
        if not exact or work_kind not in _OFFERED_WORK_KINDS:
            raise ValueError(
                "AD-1346 M3d3b2: a work-ticket finding's operation, code and work kind are exact str, and its work kind "
                "is in WORK_KINDS or empty"
            )
        now = self._wall_clock()
        hour = self._hour_of(now)
        self._totals["ticket_offered"] += 1
        self._ticket_offered[hour] = self._ticket_offered.get(hour, 0) + 1
        key = (hour, operation, code, work_kind, off_loop)
        if key in self._ticket_findings:
            self._ticket_findings[key] += 1
        elif len(self._ticket_findings) < PENDING_KEY_LIMIT:
            self._ticket_findings[key] = 1
        else:
            self._totals["ticket_dropped"] += 1
            self._ticket_dropped[hour] = self._ticket_dropped.get(hour, 0) + 1
            return
        if code in _COUNTED_ONLY:
            return
        missing = code == TICKET_MISSING
        buffer = self._ticket_missing if missing else self._ticket_samples
        if len(buffer) < (TICKET_MISSING_BUFFER_LIMIT if missing else TICKET_SAMPLE_BUFFER_LIMIT):
            buffer.append(TicketSample(hour, now, finding, off_loop))
        else:
            self._totals["ticket_samples_dropped"] += 1
            self._ticket_samples_dropped[hour] = self._ticket_samples_dropped.get(hour, 0) + 1

    def _hour_of(self, now: float) -> str:
        index = int(now // _HOUR_SECONDS)
        if index != self._hour_index:
            self._hour_index = index
            self._hour = utc_hour(index * _HOUR_SECONDS)
        return self._hour

    def start(self) -> None:
        """Mark the current hour for this boot's marker row and, from AD-1346 M3d3b2, its work-ticket marker row, and start the flusher task.

        Raises ``RuntimeError`` when it has already started or ``stop`` began.
        """
        if self._task is not None or self._stopping:
            raise RuntimeError("AD-1346 M3b: a shadow recorder starts once")
        hour = self._hour_of(self._wall_clock())
        self._offered.setdefault(hour, 0)
        self._ticket_offered.setdefault(hour, 0)  # AD-1346 M3d3b2 (D153): the boot's work-ticket marker row too
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
                # back or written; the next tick flushes again. Counted, not logged, because the log call
                # may be what raised.
                self._totals["flush_errors"] += 1

    async def stop(self) -> None:
        """Refuse later offers of verdicts and of work-ticket findings, let the flusher end after its last flush, then flush what is still pending.

        It waits for the flusher without cancelling it, so this call interrupts no write. Then it
        flushes while anything is pending, at most ``STOP_FLUSH_ATTEMPTS`` times (each flush writes at
        most twice, D150), and logs a warning with the counts of the verdicts, samples, work-ticket
        findings and work-ticket samples that were not written. A write that raises an ``Exception``
        is counted and logged by the flush; it is not raised here.
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
                "AD-1346 M3b, M3d3b2: %d shadow verdicts, %d samples, %d work-ticket findings and %d work-ticket "
                "samples were not written before the recorder stopped",
                sum(self._aggregates.values()), len(self._samples), sum(self._ticket_findings.values()),
                len(self._ticket_samples) + len(self._ticket_missing),
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
        tickets = TicketBatch(
            self._ticket_findings, self._ticket_samples, self._ticket_missing, self._ticket_offered,
            self._ticket_dropped, self._ticket_samples_dropped,
        )
        batch = ShadowBatch(
            self._aggregates, self._samples, self._offered, self._dropped, self._samples_dropped,
            parity=self._parity, disagreements=self._disagreements, tickets=tickets,
        )
        self._aggregates, self._samples, self._offered, self._dropped, self._samples_dropped = {}, [], {}, {}, {}
        self._parity, self._disagreements = {}, []
        self._ticket_findings, self._ticket_samples, self._ticket_missing = {}, [], []
        self._ticket_offered, self._ticket_dropped, self._ticket_samples_dropped = {}, {}, {}
        try:
            written = await self._store.write_batch(self._boot_id, batch)
        except BaseException as exc:
            if isinstance(exc, Exception) and (tickets.findings or tickets.samples or tickets.missing):
                await self._write_without_ticket_rows(batch)  # D150: written without its ticket rows, or put back whole
                self._failed("write")
                return
            self._restore(batch)
            if not isinstance(exc, Exception):
                raise
            self._failed("write")
            return
        self._totals["written"] += written
        self._totals["ticket_written"] += sum(tickets.findings.values())

    async def _write_without_ticket_rows(self, batch: ShadowBatch) -> None:
        """AD-1346 M3d3b2 (D150): after a write of ``batch`` raised, write it again at once with its work-ticket finding
        counts and samples counted as dropped in its work-ticket markers in place of their rows.

        When that write raises too, ``batch`` is put back whole; an ``Exception`` is then counted and logged by
        ``_failed``, and a ``BaseException`` that is not an ``Exception`` propagates.
        """
        tickets = batch.tickets
        try:
            written = await self._store.write_batch(self._boot_id, replace(batch, tickets=_as_dropped(tickets)))
        except BaseException as exc:
            self._restore(batch)
            if not isinstance(exc, Exception):
                raise
            self._failed("write")
            return
        self._totals["written"] += written
        self._totals["ticket_dropped"] += sum(tickets.findings.values())
        self._totals["ticket_samples_dropped"] += len(tickets.samples) + len(tickets.missing)

    def _restore(self, batch: ShadowBatch) -> None:
        """Add a batch that was not written back to what is pending, keeping at most ``SAMPLE_BUFFER_LIMIT`` samples and ``DISAGREEMENT_BUFFER_LIMIT`` disagreements.

        AD-1346 M3d3b2: its work-ticket part too, keeping at most ``TICKET_SAMPLE_BUFFER_LIMIT`` and
        ``TICKET_MISSING_BUFFER_LIMIT`` samples, the batch's first; each sample beyond them is counted as
        ticket_samples_dropped.
        """
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
        tickets = batch.tickets  # AD-1346 M3d3b2 (D150, D151): the work-ticket part, back within its two buffers
        _add(self._ticket_findings, tickets.findings)
        _add(self._ticket_offered, tickets.offered)
        _add(self._ticket_dropped, tickets.dropped)
        _add(self._ticket_samples_dropped, tickets.samples_dropped)
        samples, missing = tickets.samples + self._ticket_samples, tickets.missing + self._ticket_missing
        self._totals["ticket_samples_dropped"] += max(0, len(samples) - TICKET_SAMPLE_BUFFER_LIMIT)
        self._totals["ticket_samples_dropped"] += max(0, len(missing) - TICKET_MISSING_BUFFER_LIMIT)
        self._ticket_samples = _first(samples, TICKET_SAMPLE_BUFFER_LIMIT, self._ticket_samples_dropped)
        self._ticket_missing = _first(missing, TICKET_MISSING_BUFFER_LIMIT, self._ticket_samples_dropped)

    def _pending(self) -> bool:
        return bool(
            self._aggregates or self._samples or self._offered or self._dropped or self._samples_dropped
            or self._parity or self._disagreements
            or self._ticket_findings or self._ticket_samples or self._ticket_missing or self._ticket_offered
            or self._ticket_dropped or self._ticket_samples_dropped
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
