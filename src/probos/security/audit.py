"""AD-456: AuditLog -- append-only hash-chained record.

Each entry carries the SHA-256 of the prior entry, so tampering breaks the
chain and ``verify_chain()`` sees it. AD-456d added the SQLite sink
(``AuditLogPersistence``); AD-1278 (BF-780) made that sink the shipped default
and made the record survive the process -- appends go to ONE bounded queue
drained by ONE writer task, ``startup/shutdown.py`` flushes that writer before
exit, and ``entries`` is capped by FIFO eviction of rows the sink has confirmed.

Three properties a reader should not have to infer:

* **Durability is preferred, not required.** A deployment with
  ``security_infra.audit_enabled`` off, or whose sink fails mid-run, still
  executes: making the sink a precondition would turn the accountability trail
  into a new way to lose work. The cost is stated rather than hidden --
  ``durable_stream_open()`` lets a caller label its own result, so a run whose
  record will not reach disk says so where it is read.
* **The persisted sequence stream never gains a hole.** An entry that cannot
  enter the write queue SPILLS rather than dropping, and a batch the sink
  refused is retried rather than skipped; when retries are exhausted the
  durable stream ENDS instead of continuing past the gap. ``prior_hash`` chains
  each row to its predecessor, so a missing sequence would leave every later
  row pointing at a row that is not there -- a chain that reports itself
  ``broken`` at every future boot. One that stops says plainly where it ended.
* **Truncation is not tampering.** Eviction advances ``_truncated_at`` and
  ``verify_chain()`` anchors its walk there instead of at genesis, so a capped
  log verifies as intact. ``chain_state()`` is what distinguishes a complete
  chain from a truncated one; conflating the two would have the control cry
  tamper on every boot until nobody believed it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from probos.events import EventType

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuditEntry:
    """One hash-chained audit record."""

    sequence: int
    timestamp: float
    category: str
    detail: str
    prior_hash: str
    entry_hash: str


# AD-1278: how long ``drain`` waits for the writer to acknowledge its own
# cancellation, after the configured flush budget has already expired. Not an
# operator knob -- it bounds a task that has been told to stop, not the work.
_WRITER_CANCEL_GRACE_SECONDS = 1.0

# AD-1278: backoff between attempts at a batch the sink refused. Small because
# the whole teardown budget is ten seconds and a retry that outlives shutdown
# saves nothing.
_WRITE_RETRY_BACKOFF_SECONDS = 0.05

# AD-1278: how often ``flush``/``drain`` re-check quiescence once the queue
# itself has emptied. ``Queue.join`` cannot see the overflow spill or a batch
# being retried, so it is necessary but not sufficient. Only reached when one
# of those is non-empty, which is the degraded path.
_QUIESCE_POLL_SECONDS = 0.005

# BF-861 (#1331): why the stream ended, when it ended at the spill ceiling
# rather than at a refusing sink. The operator's remedy differs -- a slow sink
# versus a broken one -- so the two causes are not collapsed into one message.
_SPILL_CEILING_REASON = (
    "the overflow spill reached its ceiling, so the sink is not merely slow"
)


@dataclass
class AuditLog:
    """Hash-chained append-only log with a durable-preferred SQLite sink.

    Each entry's hash includes the prior entry's hash so any tampering breaks
    the chain. ``verify_chain()`` re-derives every hash and confirms continuity.

    AD-456d added ``attach_persistence(...)``. AD-1278 replaced its
    per-append ``create_task`` with one bounded queue and one long-lived writer:
    a thousand appends against a wedged sink used to mint a thousand tasks, and
    a queue that cannot be starved of workers is also a queue whose depth is a
    number somebody can read.

    Eviction policy (AD-1278). ``max_entries`` bounds MEMORY and nothing else,
    and it is FIFO from the head so the surviving suffix stays contiguous and
    verifiable. What it may evict depends on whether a durable copy was ever
    promised: with no sink attached the log is a ring buffer BY THE OPERATOR'S
    CHOICE and eviction is normal, while with a sink attached and behind
    nothing above ``_persisted_through`` is touched -- an entry somebody was
    told would be durable, and which is not yet durable, is the one thing
    eviction must never destroy. Eviction advances ``_truncated_at``, which
    becomes the substitute genesis for ``verify_chain()`` -- see
    ``mark_truncated``.

    That gate is only sound because the confirmed stream is contiguous:
    overflow spills instead of dropping, a refused batch is retried rather than
    skipped, and ``mark_persisted_through`` refuses a jump. A watermark that
    stepped over a hole would delete precisely the entries the gate exists to
    protect.
    """

    entries: list[AuditEntry] = field(default_factory=list)
    emit_event: Any | None = None
    # AD-456d: optional persistence seam. Defaults None preserve AD-456
    # in-memory-only contract. Set via ``attach_persistence(...)``.
    _persistence: "AuditLogPersistence | None" = None

    GENESIS_HASH: str = "0" * 64

    # AD-1278: memory bound on ``entries``. ``<= 0`` disables it.
    max_entries: int = 10_000
    # AD-1278: bound on entries awaiting the sink. A full queue holds the entry
    # in memory and says so; it never blocks and never fails an append.
    write_queue_maxsize: int = 1000
    # BF-861 (#1331): ceiling on the overflow spill. Reached means the sink has
    # fallen this far behind, and the stream ENDS rather than sheds -- dropping
    # would restore the chain hole the spill exists to prevent. ``<= 0``
    # disables the ceiling and restores the unbounded behaviour.
    spill_maxsize: int = 10_000
    # AD-1278: ``(sequence, entry_hash)`` of the last entry evicted from
    # ``entries``. None means the list still starts at genesis.
    _truncated_at: tuple[int, str] | None = None
    _queue: "asyncio.Queue[AuditEntry] | None" = None
    _writer_task: "asyncio.Task[None] | None" = None
    _writer_closed: bool = False
    # Highest sequence the sink has confirmed, and highest handed to the queue.
    # Their difference is what shutdown reports as lost when the drain expires.
    _persisted_through: int = -1
    _enqueued_through: int = -1
    _inflight: int = 0
    _spilled: int = 0
    _queue_full_warned: bool = False
    _cap_pressure_warned: bool = False
    # AD-1278: consecutive failures tolerated on ONE batch before the durable
    # stream is ended rather than continued past the gap.
    write_max_retries: int = 3
    # AD-1278: entries that could not enter the queue, and the batch the sink
    # is currently refusing. Both hold references ``entries`` is already
    # retaining (an unconfirmed entry is not evictable), so the cost is roughly
    # a pointer each. Appended last: every field carries a default and every
    # construction site is keyword, but reordering a dataclass is still a
    # silent break for anyone who did not.
    _spill: "deque[AuditEntry]" = field(default_factory=deque)
    _retry_batch: list[AuditEntry] = field(default_factory=list)
    # Sequence at which the durable stream ended. Not None means nothing more
    # is written, so the on-disk chain stops cleanly instead of gaining a hole.
    _stream_broken_at: int | None = None

    # ── append ────────────────────────────────────────────────────────────

    def append(self, *, category: str, detail: str) -> AuditEntry:
        prior_hash = (
            self.entries[-1].entry_hash if self.entries else self._anchor_hash()
        )
        sequence = self._next_sequence()
        ts = time.time()
        payload = {
            "sequence": sequence,
            "timestamp": ts,
            "category": category,
            "detail": detail,
            "prior_hash": prior_hash,
        }
        entry_hash = self._hash(payload)
        entry = AuditEntry(
            sequence=sequence,
            timestamp=ts,
            category=category,
            detail=detail,
            prior_hash=prior_hash,
            entry_hash=entry_hash,
        )
        self.entries.append(entry)
        if self.emit_event is not None:
            try:
                self.emit_event(
                    EventType.AUDIT_RECORDED,
                    {
                        "sequence": sequence,
                        "category": category,
                        "entry_hash": entry_hash,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-456: AUDIT_RECORDED emit failed (sequence=%d, category=%s)",
                    sequence, category, exc_info=True,
                )
        self._schedule_persist(entry)
        self._enforce_cap()
        return entry

    def durable_stream_open(self) -> bool:
        """Whether an append would be ADMITTED to the durable stream.

        Exact about admission and silent about commitment, and the distinction
        is the whole of AD-1278 revision 3. A sink is attached, the writer is
        open, the stream has not ended -- that is a fact about now, observed
        with no await in between, so a caller may read it, append, and label its
        own result. It is NOT a promise that this entry reaches disk: the writer
        commits later, and a caller that wrote ``durable`` down on the strength
        of this would be recording a forecast as an outcome.

        Callers therefore say ``"queued"``, never ``"durable"``. What attests
        an entry's durability is its row in SQLite, and that lives in the DB.
        """
        if self._persistence is None or self._writer_closed:
            return False
        if self._stream_broken_at is not None:
            return False
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return False
        return True

    # ── chain ─────────────────────────────────────────────────────────────

    def verify_chain(self) -> bool:
        """Re-derive every entry hash; return True if the chain is intact.

        AD-1278: the walk starts at ``_truncated_at`` when the head has been
        evicted, so a bounded log reports as intact rather than as tampered.
        Truncation and tampering are different failures and a control that
        conflated them would be lying in the more damaging direction.
        """
        prior = self._anchor_hash()
        for entry in self.entries:
            payload = {
                "sequence": entry.sequence,
                "timestamp": entry.timestamp,
                "category": entry.category,
                "detail": entry.detail,
                "prior_hash": entry.prior_hash,
            }
            recomputed = self._hash(payload)
            if recomputed != entry.entry_hash or entry.prior_hash != prior:
                return False
            prior = entry.entry_hash
        return True

    def chain_state(self) -> tuple[str, int, int]:
        """``(state, first_sequence, evicted_count)`` -- the richer answer.

        ``state`` is ``"intact"``, ``"truncated"`` or ``"broken"``.
        ``verify_chain()`` deliberately keeps returning True for a correctly
        truncated chain, so this is how a verifier tells a bounded log from a
        complete one. Once a watermark exists the state is never ``"intact"``:
        silent truncation reported as complete is the same lie the other way up.
        """
        evicted = (self._truncated_at[0] + 1) if self._truncated_at is not None else 0
        first_sequence = self.entries[0].sequence if self.entries else evicted
        if not self.verify_chain():
            return ("broken", first_sequence, evicted)
        if self._truncated_at is not None:
            return ("truncated", first_sequence, evicted)
        return ("intact", first_sequence, evicted)

    def mark_truncated(self, sequence: int, entry_hash: str) -> None:
        """Anchor the chain at the last entry that left ``entries`` (AD-1278).

        Forward-only, and it raises rather than degrading: an anchor a caller
        could move freely would let tampering pass as truncation -- point it at
        the break and a mutated chain verifies as intact. Reached by the
        eviction path, and once at boot when a bounded rehydrate legitimately
        does not start at genesis.
        """
        current = self._truncated_at
        if current is not None and int(sequence) <= current[0]:
            raise ValueError(
                "AD-1278: the truncation watermark is forward-only "
                f"(anchored at sequence {current[0]}, refused {sequence})"
            )
        self._truncated_at = (int(sequence), str(entry_hash))

    def mark_persisted_through(self, sequence: int) -> None:
        """Record that every entry up to ``sequence`` is confirmed on disk.

        Monotonic AND contiguous. Monotonic because eviction reads it to decide
        what may be dropped and a backwards move would make an unpersisted entry
        look evictable. Contiguous because this one integer is a claim about a
        RANGE, and a range property inferred from a point observation is only
        true if the confirmed stream has no holes.

        The guard is deliberately kept even though the spill (A1) and the batch
        retry (A2) make a hole unreachable by construction: "unreachable by
        construction" is exactly what the previous revision's mutation matrix
        believed, and one comparison turns a design argument into a runtime
        invariant.

        The first advance from ``-1`` SEEDS rather than steps -- there is no
        predecessor to be contiguous with, and the caller is either the boot
        rehydrate (which read those rows off disk) or the writer's first
        confirmation. It is floored at the log's own first sequence.
        """
        seq = int(sequence)
        if seq <= self._persisted_through:
            return
        if self._persisted_through >= 0:
            if seq != self._persisted_through + 1:
                # A jump means the confirmed stream has a hole, and one integer
                # cannot represent one. Refusing keeps eviction honest;
                # accepting it is how the only copy of an unpersisted entry
                # gets deleted.
                logger.error(
                    "AD-1278: refusing a non-contiguous durability watermark "
                    "(confirmed through %d, asked to advance to %d). Sequences "
                    "%d-%d were never confirmed, so they stay in memory and "
                    "stay unevictable; the persisted chain has a gap.",
                    self._persisted_through, seq,
                    self._persisted_through + 1, seq - 1,
                )
                return
        elif seq < self._floor_sequence():
            # Seeding below the first sequence this log holds confirms nothing.
            return
        self._persisted_through = seq
        self._enforce_cap()

    # ── persistence ───────────────────────────────────────────────────────

    def attach_persistence(self, persistence: "AuditLogPersistence") -> None:
        """AD-456d: Attach an ``AuditLogPersistence`` instance.

        Pure setter — no other side effects. After attachment, each subsequent
        ``append()`` enqueues the entry for the single writer when a running
        asyncio loop is present. Mirrors ``OracleService.attach_semantic_layer``
        shape from AD-686b.
        """
        self._persistence = persistence

    async def flush(self, *, timeout_seconds: float = 2.0) -> None:
        """Wait until every queued entry has been handed to the sink.

        AD-1278's synchronisation point, replacing the ``_pending_writes`` task
        set: with one writer there is no set of tasks to gather, so a caller
        that needs the rows on disk waits on the queue instead. Registration
        stays open -- ``drain`` is the shutdown-time version that closes it.

        BOUNDED, and revision 3 made it so: shutdown phase 1 calls this inside a
        ten-second whole-teardown budget, and a bare ``queue.join()`` against a
        wedged sink is a hang waiting to happen. On expiry it logs and returns
        so the caller can proceed -- ``drain`` tries again with the full budget.
        ``asyncio.wait``, never ``asyncio.wait_for``, for the reason ``drain``
        documents.
        """
        if self._queue is None:
            return
        loop = asyncio.get_running_loop()
        budget = max(0.0, float(timeout_seconds))
        waiter = loop.create_task(self._await_quiescent(), name="audit-log-flush")
        done, _pending = await asyncio.wait({waiter}, timeout=budget)
        if waiter in done:
            return
        waiter.cancel()
        await asyncio.wait({waiter}, timeout=_WRITER_CANCEL_GRACE_SECONDS)
        logger.warning(
            "AD-1278: the audit flush did not quiesce within %.1fs; %d "
            "entr%s are still unconfirmed. Registration stays OPEN, so the "
            "shutdown drain gets another attempt at them.",
            budget, self._unflushed(),
            "y is" if self._unflushed() == 1 else "ies are",
        )

    async def drain(self, *, timeout_seconds: float = 2.0) -> int:
        """Close registration, flush the writer, and return what was left.

        Bounded on purpose: ``__main__.py`` gives the WHOLE teardown ten
        seconds, so a drain that hangs shutdown is a worse defect than the tail
        it saves. On expiry the writer is cancelled and the loss is logged at
        ERROR with the sequence range, because an unstated loss is how a
        best-effort control passes for a guarantee.

        ``asyncio.wait`` rather than ``asyncio.wait_for``: on timeout
        ``wait_for`` cancels the inner task and then awaits it UNBOUNDED, so a
        writer that caught ``CancelledError`` to finish a final commit would
        hang the process here forever.
        """
        self._writer_closed = True
        queue = self._queue
        task = self._writer_task
        if queue is None or task is None or task.done():
            self._writer_task = None
            return self._unflushed()

        loop = asyncio.get_running_loop()
        budget = max(0.0, float(timeout_seconds))
        joiner = loop.create_task(self._await_quiescent(), name="audit-log-drain")
        try:
            done, _pending = await asyncio.wait({joiner}, timeout=budget)
        except asyncio.CancelledError:
            # The outer teardown budget fired. Cancellation belongs to the
            # shutdown, not to this drain: stop the writer and get out of the
            # way rather than absorbing it.
            joiner.cancel()
            task.cancel()
            raise
        if joiner not in done:
            joiner.cancel()
            await asyncio.wait({joiner}, timeout=_WRITER_CANCEL_GRACE_SECONDS)

        unflushed = self._unflushed()
        task.cancel()
        await asyncio.wait({task}, timeout=_WRITER_CANCEL_GRACE_SECONDS)
        if not task.done():
            logger.error(
                "AD-1278: the audit writer did not stop within %.1fs of "
                "cancellation; abandoning it so teardown can continue. Any "
                "entry it still holds is not confirmed on disk.",
                _WRITER_CANCEL_GRACE_SECONDS,
            )
        self._writer_task = None
        if unflushed:
            logger.error(
                "AD-1278: audit drain expired after %.1fs with %d unflushed "
                "entr%s; sequences %d-%d are NOT confirmed on disk and are lost "
                "at process exit. The sink did not keep up with shutdown.",
                budget, unflushed, "y" if unflushed == 1 else "ies",
                self._persisted_through + 1, self._enqueued_through,
            )
        return unflushed

    # ── internals ─────────────────────────────────────────────────────────

    def _anchor_hash(self) -> str:
        return (
            self._truncated_at[1]
            if self._truncated_at is not None
            else self.GENESIS_HASH
        )

    def _next_sequence(self) -> int:
        # NOT ``len(self.entries)``: eviction breaks that identity, and a
        # sequence that rewound would collide with a persisted row.
        if self.entries:
            return self.entries[-1].sequence + 1
        if self._truncated_at is not None:
            return self._truncated_at[0] + 1
        return 0

    def _unflushed(self) -> int:
        queue = self._queue
        return (
            (queue.qsize() if queue is not None else 0)
            + len(self._spill)
            + self._inflight
        )

    def _floor_sequence(self) -> int:
        """The lowest sequence this log still accounts for."""
        if self.entries:
            return self.entries[0].sequence
        if self._truncated_at is not None:
            return self._truncated_at[0] + 1
        return 0

    async def _await_quiescent(self) -> None:
        """Return once the queue, the spill and the writer are all empty.

        ``Queue.join()`` alone is not the answer: it cannot see an entry sitting
        in the overflow spill or a batch the writer is retrying, and returning
        while either holds an entry would let a caller believe the rows landed.
        The poll below is only reached when one of them is non-empty.
        """
        queue = self._queue
        if queue is None:
            return
        while True:
            await queue.join()
            if not self._spill and not self._retry_batch and self._inflight == 0:
                return
            if self._stream_broken_at is not None:
                # Nothing more will be written, so waiting is waiting forever.
                return
            await asyncio.sleep(_QUIESCE_POLL_SECONDS)

    def _schedule_persist(self, entry: AuditEntry) -> None:
        if self._persistence is None:
            return
        if self._stream_broken_at is not None:
            logger.debug(
                "AD-1278: the durable audit stream ended at sequence %d "
                "(sequence=%d); the entry is held in memory only",
                self._stream_broken_at, entry.sequence,
            )
            return
        if self._writer_closed:
            logger.debug(
                "AD-1278: the audit writer is closed (sequence=%d); the entry "
                "is held in memory only",
                entry.sequence,
            )
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug(
                "AD-456d: AuditLog.append called without running loop "
                "(sequence=%d); persistence skipped",
                entry.sequence,
            )
            return
        queue = self._ensure_writer(loop)
        if self._spill:
            # Once anything has overflowed, everything behind it takes the same
            # route. A later entry that slipped into the queue would be written
            # BEFORE the spilled one, and a reordered stream is a stream with a
            # hole in it for as long as the reordering lasts.
            self._spill.append(entry)
            self._note_spill(entry, queue)
        else:
            try:
                queue.put_nowait(entry)
            except asyncio.QueueFull:
                self._spill.append(entry)
                self._note_spill(entry, queue)
        self._enqueued_through = entry.sequence

    def _note_spill(
        self, entry: AuditEntry, queue: "asyncio.Queue[AuditEntry]",
    ) -> None:
        self._spilled += 1
        if not self._queue_full_warned:
            self._queue_full_warned = True
            logger.warning(
                "AD-1278: the audit write queue is full (maxsize=%d); entry %d "
                "and any that follow are held in an overflow buffer until the "
                "sink catches up. They are NOT dropped -- a dropped sequence "
                "would leave the next persisted row chained to a row that is "
                "not there. The sink is not keeping up with appends.",
                queue.maxsize, entry.sequence,
            )
        ceiling = int(self.spill_maxsize)
        if ceiling > 0 and len(self._spill) > ceiling:
            # BF-861 (#1331): spilling instead of dropping is what keeps the
            # chain hole-free, and it is also what made this buffer unbounded.
            # At the ceiling the stream ENDS rather than shedding: dropping
            # here would put back the hole the spill exists to prevent, so the
            # only bounded option that keeps the guarantee is to stop.
            #
            # Reported at `_persisted_through + 1`, NOT at the spill head:
            # terminating also discards the queue, whose sequences sit BELOW
            # the spill's. Naming the spill head would claim those queued
            # sequences reached disk when they were dropped -- overstating the
            # durable end by up to `write_queue_maxsize`.
            self._terminate_stream(
                self._persisted_through + 1, _SPILL_CEILING_REASON,
            )

    def _ensure_writer(self, loop: asyncio.AbstractEventLoop) -> "asyncio.Queue[AuditEntry]":
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=max(1, int(self.write_queue_maxsize)))
        if self._writer_task is None or self._writer_task.done():
            # A writer that died takes every later append down with it, so it is
            # replaced rather than mourned. One task, not one per append.
            self._writer_task = loop.create_task(
                self._writer_loop(), name="audit-log-writer",
            )
        return self._queue

    async def _next_batch(
        self, queue: "asyncio.Queue[AuditEntry]",
    ) -> tuple[list[AuditEntry], int]:
        """The next contiguous run to commit, and how many came off the queue.

        Queue entries are always OLDER than spilled ones (nothing enters the
        queue while the spill is non-empty), so the queue leads and the spill
        follows. The count is what ``task_done`` is owed; spilled entries were
        never queued and must not be acknowledged there.
        """
        batch: list[AuditEntry] = []
        if not self._spill:
            batch.append(await queue.get())
        while True:
            try:
                batch.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        queue_taken = len(batch)
        while self._spill:
            batch.append(self._spill.popleft())
        return batch, queue_taken

    async def _commit_batch(
        self, persistence: "AuditLogPersistence", batch: list[AuditEntry],
    ) -> Sequence[int]:
        """Commit one batch, retrying it in place until it lands or the stream ends.

        Retried in place rather than requeued: there is exactly one writer, so
        holding the batch here IS holding it at the head of the stream and
        nothing can be committed past it. Skipping to the next batch is what
        revision 2 did, and because ``persist_entries`` is all-or-nothing the
        next success then confirmed a HIGHER range than the failure -- a hole
        that survives a perfectly behaved queue.
        """
        attempts = max(0, int(self.write_max_retries))
        self._retry_batch = batch
        try:
            for attempt in range(attempts + 1):
                try:
                    confirmed = await persistence.persist_entries(batch)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    confirmed = ()
                    logger.warning(
                        "AD-1278: the audit writer's batch of %d raised on "
                        "attempt %d of %d; retrying the SAME batch rather than "
                        "moving on, because a skipped batch leaves the next "
                        "persisted row chained to a row that is not there",
                        len(batch), attempt + 1, attempts + 1, exc_info=True,
                    )
                if confirmed:
                    return confirmed
                if attempt < attempts:
                    await asyncio.sleep(_WRITE_RETRY_BACKOFF_SECONDS)
            # Report the WATERMARK, not the batch head. Those coincide only for
            # an all-or-nothing sink; one that under-reports leaves the head
            # climbing while the watermark stalls, and review reproduced
            # `stream_broken_at 4` against `persisted_through 0` -- the reported
            # end overstating the durable end, which is the one direction this
            # number must never move. The head stays in the message for
            # diagnostics.
            self._terminate_stream(
                self._persisted_through + 1,
                f"the sink refused sequence {batch[0].sequence} on "
                f"{attempts + 1} consecutive attempts",
            )
            return ()
        finally:
            self._retry_batch = []

    def _terminate_stream(self, sequence: int, cause: str) -> None:
        """End the durable stream rather than write past a gap.

        Deliberately terminal, and the trade is the point: a durable chain with
        a hole is worth LESS than one that stops. The first lies about its own
        integrity at every future boot -- every row after the gap reports
        ``broken`` -- while the second says plainly where it ended and
        rehydrates cleanly. Recovery needs a restart; every run until then
        labels itself ``in-memory-only``.

        ``cause`` distinguishes the two ways to get here -- a sink that refused
        a batch, or the BF-861 spill ceiling -- because the operator's remedy
        differs and a single message would send them after the wrong one.

        FIRST TERMINATION WINS (BF-861). With two call sites the second would
        overwrite the first, and both directions are wrong: forwards it claims
        the intervening sequences reached disk, backwards it hides ones that
        did. This number is what an operator reads to learn where the on-disk
        chain ends.
        """
        if self._stream_broken_at is not None:
            return
        self._stream_broken_at = int(sequence)
        logger.error(
            "AD-1278: ENDING the durable audit stream at sequence %d (%s). "
            "Nothing further is enqueued, so the persisted chain stops cleanly "
            "instead of gaining a hole that would report as tampering forever. "
            "Every execution from now on is labelled in-memory-only; restart "
            "to recover.",
            sequence, cause,
        )
        self._spill.clear()
        # BF-861: DISOWN whatever the writer is still holding. The alternative
        # -- waiting for it to fall idle -- makes the memory bound depend on
        # the liveness of the component that is already wedged, which is how
        # the second attempt at this reintroduced unbounded growth.
        #
        # Safe because eviction cannot reach the batch: `_next_batch` holds it
        # in its own list and `AuditEntry` is frozen, so `del self.entries[:n]`
        # drops slots, not entries. A disowned batch that goes on to commit
        # simply ends the disk chain one batch later, still contiguous -- which
        # is why the log message says ENQUEUED rather than written.
        self._inflight = 0
        self._retry_batch = []
        queue = self._queue
        if queue is None:
            return
        # Release the join() counter: nothing will consume these now, and a
        # flush left waiting on them would burn the whole teardown budget.
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            queue.task_done()

    async def _writer_loop(self) -> None:
        queue = self._queue
        persistence = self._persistence
        if queue is None or persistence is None:
            return
        while True:
            batch, queue_taken = await self._next_batch(queue)
            self._inflight = len(batch)
            try:
                confirmed = await self._commit_batch(persistence, batch)
            finally:
                self._inflight = 0
                for _ in range(queue_taken):
                    queue.task_done()
            self._advance_persisted(confirmed)
            if self._stream_broken_at is not None:
                return

    def _advance_persisted(self, confirmed: Sequence[int]) -> None:
        """Step the watermark one sequence at a time, stopping at the first gap.

        ``max(confirmed)`` was Critical 1: it turns \"this batch committed\" --
        a point observation -- into \"everything at or below this is on disk\",
        a range property. Walking the run lets ``mark_persisted_through``
        refuse a jump instead of the caller asserting one.
        """
        for seq in sorted(confirmed):
            if seq <= self._persisted_through:
                continue
            self.mark_persisted_through(seq)
            if self._persisted_through != seq:
                break

    def _enforce_cap(self) -> None:
        cap = int(self.max_entries)
        if cap <= 0:
            return
        excess = len(self.entries) - cap
        if excess <= 0:
            return
        if self._persistence is None or self._stream_broken_at is not None:
            # Persistence off BY CONFIGURATION: nobody was promised a durable
            # copy, so this is a ring buffer the operator chose and the
            # truncation watermark keeps the remainder verifiable. Refusing
            # here would make `max_entries` decorative in the commonest
            # deployment, which is the memory bound quietly not existing.
            #
            # BF-861 (#1331): a TERMINATED stream is the same situation arrived
            # at by failure rather than by choice. Nothing further is enqueued,
            # so holding these entries preserves no durable copy that eviction
            # would destroy -- it only trades the hole AD-1278 prevents for an
            # unbounded heap. Measured before the fix: 5000 entries at a cap
            # of 3 against a wedged sink.
            #
            # Deliberately NOT guarded on writer state. A guard reading
            # `_inflight` or `_retry_batch` never opens against a permanently
            # wedged writer, which is unbounded growth wearing a safety
            # costume; and it guards nothing, because `_terminate_stream` has
            # already disowned the batch and eviction could not reach it
            # anyway.
            self._evict(excess)
            return
        evictable = 0
        for entry in self.entries[:excess]:
            if entry.sequence > self._persisted_through:
                break
            evictable += 1
        if evictable == 0:
            if not self._cap_pressure_warned:
                self._cap_pressure_warned = True
                logger.warning(
                    "AD-1278: the audit log is %d entries over its %d cap and "
                    "none of the excess is confirmed on disk, so nothing is "
                    "evicted and memory keeps growing. Dropping the only copy "
                    "of an accountability record is not a memory-management "
                    "strategy; enable security_infra.audit_persistence_enabled "
                    "or raise the cap.",
                    excess, cap,
                )
            return
        self._evict(evictable)

    def _evict(self, count: int) -> None:
        last_evicted = self.entries[count - 1]
        self.mark_truncated(last_evicted.sequence, last_evicted.entry_hash)
        del self.entries[:count]

    def _hash(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


# ---------------------------------------------------------------------------
# AD-456d: SQLite persistence layer
# ---------------------------------------------------------------------------

# Schema mirrors ``AuditEntry`` 1-for-1. ``sequence`` is the natural primary
# key: AD-1278's ``AuditLog._next_sequence`` assigns it monotonically and never
# rewinds it, deliberately NOT from ``len(self.entries)`` -- eviction breaks
# that identity and a rewound sequence would collide with a persisted row.
# ``entry_hash`` is unique per the SHA-256-of-prior-hash chain semantics. Index
# on ``timestamp`` supports AD-456d-7 future range queries from the HXI
# inspection surface.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    sequence INTEGER PRIMARY KEY,
    timestamp REAL NOT NULL,
    category TEXT NOT NULL,
    detail TEXT NOT NULL,
    prior_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
"""


class AuditLogPersistence:
    """AD-456d: SQLite-backed persistence for ``AuditLog``.

    Cloud-ready via injected ``connection_factory: ConnectionFactory``
    (AD-466). Mirrors ``ClearanceGrantStore`` (AD-622) WAL/busy_timeout/
    synchronous PRAGMA shape exactly. Writes are append-only; reads are
    used at boot to rehydrate the in-memory chain.

    AD-1278 wired ``stop()`` into ``startup/shutdown.py`` (the AD-456d-1 that
    was deferred here) and moved the write path onto ``persist_entries``, which
    commits ONE transaction per batch. ``persist_entry`` is kept as the
    single-row spelling of the same call.
    """

    def __init__(
        self,
        *,
        db_path: str,
        connection_factory: "ConnectionFactory",
        emit_event: Any | None = None,
    ) -> None:
        self._db_path = db_path
        self._connection_factory = connection_factory
        self._emit_event = emit_event
        self._db: Any = None

    async def start(self) -> None:
        """Open the connection, set PRAGMAs, create schema."""
        self._db = await self._connection_factory.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("AD-456d: AuditLogPersistence started (db=%s)", self._db_path)

    async def stop(self) -> None:
        """Close the connection.

        AD-1278 wired this into ``startup/shutdown.py``, after
        ``AuditLog.drain`` has flushed the writer.
        """
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def persist_entries(self, entries: Sequence[AuditEntry]) -> list[int]:
        """Insert a batch in ONE transaction; return the sequences confirmed.

        AD-1278: one ``commit()`` per batch rather than per row. The returned
        sequences are what ``AuditLog`` uses to decide an entry may be evicted,
        so an empty list on failure is load-bearing -- an entry the sink did not
        confirm must stay in memory rather than be dropped.

        Tier-2 log-and-degrade — SQLite write failures NEVER propagate up to the
        sync ``append()`` caller that produced these entries. The decision is
        already chained in memory and emitted as ``AUDIT_RECORDED``; the persist
        channel is observer-only.
        """
        rows = list(entries)
        if not rows:
            return []
        if self._db is None:
            logger.warning(
                "AD-456d: persist_entry called before start() (sequence=%d)",
                rows[0].sequence,
            )
            return []
        try:
            await self._db.executemany(
                """INSERT INTO audit_log
                       (sequence, timestamp, category, detail, prior_hash, entry_hash)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        entry.sequence,
                        entry.timestamp,
                        entry.category,
                        entry.detail,
                        entry.prior_hash,
                        entry.entry_hash,
                    )
                    for entry in rows
                ],
            )
            await self._db.commit()
        except Exception:
            logger.warning(
                "AD-456d: AuditLog persist failed (sequence=%d, category=%s)",
                rows[0].sequence, rows[0].category, exc_info=True,
            )
            return []
        if self._emit_event is not None:
            for entry in rows:
                try:
                    self._emit_event(
                        EventType.AUDIT_PERSISTED,
                        {
                            "sequence": entry.sequence,
                            "entry_hash": entry.entry_hash,
                        },
                    )
                except Exception:
                    logger.warning(
                        "AD-456d: AUDIT_PERSISTED emit failed (sequence=%d)",
                        entry.sequence, exc_info=True,
                    )
        return [entry.sequence for entry in rows]

    async def persist_entry(self, entry: AuditEntry) -> None:
        """Insert one ``AuditEntry`` row — the single-row spelling of
        ``persist_entries``."""
        await self.persist_entries([entry])

    async def load_entries(self, *, limit: int = 0) -> list[AuditEntry]:
        """Return rows ordered by sequence ASC for chain rehydration.

        ORDER BY sequence is REQUIRED — without it, SQLite is permitted to
        return rows in any order, which would shuffle the prior_hash chain
        and break ``verify_chain()`` after rehydrate.

        AD-1278: ``limit`` > 0 returns the NEWEST ``limit`` rows, still
        ascending. A boot that rehydrated every row would rebuild the unbounded
        list the cap exists to prevent. Pair it with ``watermark_before`` so the
        caller can anchor the chain BEFORE verifying it — a bounded load
        legitimately does not start at genesis, and verifying it unanchored
        reports a full log as tampered.
        """
        if self._db is None:
            return []
        columns = (
            "sequence, timestamp, category, detail, prior_hash, entry_hash"
        )
        if limit and limit > 0:
            cursor = await self._db.execute(
                f"""SELECT {columns} FROM (
                        SELECT * FROM audit_log ORDER BY sequence DESC LIMIT ?
                    ) ORDER BY sequence ASC""",
                (int(limit),),
            )
        else:
            cursor = await self._db.execute(
                f"SELECT {columns} FROM audit_log ORDER BY sequence ASC"
            )
        rows = await cursor.fetchall()
        return [
            AuditEntry(
                sequence=row[0],
                timestamp=row[1],
                category=row[2],
                detail=row[3],
                prior_hash=row[4],
                entry_hash=row[5],
            )
            for row in rows
        ]

    async def watermark_before(self, sequence: int) -> tuple[int, str] | None:
        """AD-1278: the ``(sequence, entry_hash)`` immediately preceding
        ``sequence``, or None when nothing does.

        The anchor a bounded ``load_entries`` needs: it names the newest row the
        caller did NOT load, which is exactly the substitute genesis
        ``AuditLog.mark_truncated`` wants.
        """
        if self._db is None:
            return None
        cursor = await self._db.execute(
            """SELECT sequence, entry_hash FROM audit_log
               WHERE sequence < ? ORDER BY sequence DESC LIMIT 1""",
            (int(sequence),),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return (int(row[0]), str(row[1]))

    async def count(self) -> int:
        """Return total persisted rows (testability helper)."""
        if self._db is None:
            return 0
        cursor = await self._db.execute("SELECT COUNT(*) FROM audit_log")
        row = await cursor.fetchone()
        return row[0] if row else 0
