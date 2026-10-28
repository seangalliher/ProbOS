"""AD-1270 (#1324): AD-668 salience filtering and AD-670 metabolism, wired to crew working memory.

Default off. ``working_memory.cognition_enabled`` is read in one place,
:func:`build_working_memory_cognition`. Off, it returns ``None``: nothing here is constructed
and every agent's working memory behaves as it did before.

On, :class:`WorkingMemoryCognition` attaches one shared :class:`SalienceFilter` and one shared
:class:`MemoryMetabolism` (neither holds per-agent state) to each crew agent's working memory,
and every ``metabolism.cycle_interval_seconds`` runs one metabolism cycle per agent and drains
its background stream. Each cycle attaches again, so a working memory the AD-573 stasis restore
replaced, or an agent that joined later, is covered from its next cycle.

What it touches: in-memory working memory only (the rings, the named buffers and the background
stream). FORGET and TRIAGE delete no episode, Ward Room post or store record. The AD-573 freeze
sees the entries that remain, each kept ring entry carries ``_decay_score`` in its metadata, and
the frozen ``background_stream_count`` counts demoted entries the cycle has not drained yet.

The background-stream consumer counts what the salience gate demoted and discards it; it
promotes nothing back. Audit flags are counted and logged, not shown to the agent.

Log-and-degrade: a cycle that raises for one agent is logged, and the other agents and the
loop carry on. Nothing is rolled back: that agent keeps what the cycle changed before it
raised, so a named buffer can still hold an entry its ring has forgotten.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from probos.cognitive.memory_metabolism import MemoryMetabolism
from probos.cognitive.salience_filter import SalienceFilter

if TYPE_CHECKING:
    from probos.cognitive.agent_working_memory import AgentWorkingMemory
    from probos.config import MetabolismConfig, SalienceConfig, WorkingMemoryConfig

logger = logging.getLogger(__name__)

#: ``(agent id, working memory)`` for every crew agent; called again on every cycle.
WorkingMemories = Callable[[], Iterable[tuple[str, "AgentWorkingMemory"]]]


@dataclass(frozen=True)
class CognitionTickReport:
    """What one cycle did, summed over the crew."""

    agents: int
    forgotten: int
    audit_flags: int
    demoted: int
    failed: int


class WorkingMemoryCognition:
    """Attaches AD-668 and AD-670 to crew working memory and runs their cycle; one per runtime."""

    def __init__(
        self,
        *,
        working_memories: WorkingMemories,
        salience_filter: SalienceFilter | None,
        metabolism: MemoryMetabolism | None,
        background_max_entries: int,
        interval_seconds: float,
    ) -> None:
        if salience_filter is None and metabolism is None:
            raise ValueError("working-memory cognition needs a salience filter or a metabolism engine")
        if not (math.isfinite(interval_seconds) and interval_seconds > 0):
            raise ValueError("metabolism.cycle_interval_seconds must be finite and above 0")
        if background_max_entries < 0:
            raise ValueError("salience.background_max_entries must not be negative")
        self._working_memories = working_memories
        self._salience_filter = salience_filter
        self._metabolism = metabolism
        self._background_max_entries = background_max_entries
        self._interval = float(interval_seconds)
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        """True while the cycle task exists and has not finished."""
        return self._task is not None and not self._task.done()

    def attach_all(self) -> int:
        """Attach the filter and the engine to every crew working memory; return how many took it."""
        attached = 0
        for agent_id, memory in self._members():
            try:
                self._attach(memory)
            except Exception:
                logger.warning(
                    "AD-1270: could not attach working-memory cognition for %s", agent_id, exc_info=True
                )
            else:
                attached += 1
        return attached

    def tick_once(self) -> CognitionTickReport:
        """One cycle per crew agent: attach, run metabolism, drain the background stream."""
        members = self._members()
        forgotten = audit_flags = demoted = failed = 0
        for agent_id, memory in members:
            try:
                self._attach(memory)  # every cycle: a replaced or joining working memory is covered
                report = memory.run_metabolism_cycle()
                stream = memory.get_background_stream()
                drained = len(stream.drain()) if stream is not None else 0
            except Exception:
                failed += 1
                logger.warning(
                    "AD-1270: working-memory cycle failed for %s; the other agents still run",
                    agent_id,
                    exc_info=True,
                )
                continue
            agent_forgotten = report.forgotten_count if report is not None else 0
            agent_flags = len(report.audit_flags) if report is not None else 0
            if agent_forgotten or agent_flags or drained:
                logger.info(
                    "AD-1270: working memory of %s: forgotten=%d audit_flags=%d demoted=%d",
                    agent_id,
                    agent_forgotten,
                    agent_flags,
                    drained,
                )
            forgotten += agent_forgotten
            audit_flags += agent_flags
            demoted += drained
        return CognitionTickReport(
            agents=len(members),
            forgotten=forgotten,
            audit_flags=audit_flags,
            demoted=demoted,
            failed=failed,
        )

    async def start(self) -> None:
        """Attach now, then run a cycle after every interval. Idempotent."""
        if self.running:
            return
        self.attach_all()
        self._task = asyncio.create_task(self._loop(), name="ad1270-working-memory-cognition")

    async def stop(self) -> None:
        """Cancel the cycle task and wait for it to end. Idempotent.

        Only the cancellation it caused is absorbed. The caller's cancel count is compared with
        its count at entry, as BF-881's shutdown helper does: shutdown is typically awaited from
        a task that was already cancelled (BF-303: the operator's Ctrl+C), whose count stays
        above zero for the whole teardown. A cancellation that arrives while this waits
        propagates (Async Discipline); the cycle task has ended by then.
        """
        task = self._task
        if task is None:
            return
        current = asyncio.current_task()
        cancelling_at_entry = current.cancelling() if current is not None else 0
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            if current is not None and current.cancelling() > cancelling_at_entry:
                raise

    def _members(self) -> list[tuple[str, AgentWorkingMemory]]:
        try:
            return list(self._working_memories())
        except Exception:
            logger.warning(
                "AD-1270: could not list crew working memory; this cycle does nothing", exc_info=True
            )
            return []

    def _attach(self, memory: AgentWorkingMemory) -> None:
        memory.attach_cognition(
            salience_filter=self._salience_filter,
            metabolism=self._metabolism,
            background_max_entries=self._background_max_entries,
        )

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                self.tick_once()
            except Exception:
                logger.warning("AD-1270: working-memory cycle raised; the next one runs on time", exc_info=True)


def build_working_memory_cognition(
    *,
    working_memory: WorkingMemoryConfig,
    salience: SalienceConfig,
    metabolism: MetabolismConfig,
    working_memories: WorkingMemories,
) -> WorkingMemoryCognition | None:
    """Read ``working_memory.cognition_enabled``; this is the one place it is read.

    Off: returns ``None`` and constructs nothing. On: builds the shared filter and engine from
    their own sections, where ``salience.enabled`` and ``metabolism.enabled`` each turn their part
    off, and the driver, whose period is ``metabolism.cycle_interval_seconds``. Raises
    ``ValueError`` for a value that would spin the cycle, raise on an agent's record path or make
    a gate refuse every entry; the caller logs it and leaves cognition off.
    """
    if not working_memory.cognition_enabled:
        return None
    salience_filter = _build_salience_filter(salience) if salience.enabled else None
    engine = _build_metabolism(metabolism) if metabolism.enabled else None
    if salience_filter is None and engine is None:
        logger.info(
            "AD-1270: working_memory.cognition_enabled is on, but salience and metabolism are both "
            "disabled; nothing is attached"
        )
        return None
    return WorkingMemoryCognition(
        working_memories=working_memories,
        salience_filter=salience_filter,
        metabolism=engine,
        background_max_entries=salience.background_max_entries,
        interval_seconds=metabolism.cycle_interval_seconds,
    )


def _build_salience_filter(config: SalienceConfig) -> SalienceFilter:
    if not (0.0 <= config.threshold <= 1.0):
        raise ValueError("salience.threshold must be between 0 and 1")
    return SalienceFilter.from_config(config)


def _build_metabolism(config: MetabolismConfig) -> MemoryMetabolism:
    if not math.isfinite(config.decay_half_life_seconds):
        raise ValueError("metabolism.decay_half_life_seconds must be finite")
    if not (0.0 <= config.triage_fullness_threshold < 1.0):
        raise ValueError("metabolism.triage_fullness_threshold must be at least 0 and below 1")
    if not (0.0 <= config.triage_base_score <= 1.0):
        raise ValueError("metabolism.triage_base_score must be between 0 and 1")
    return MemoryMetabolism(
        decay_half_life_seconds=config.decay_half_life_seconds,
        forget_threshold=config.forget_threshold,
        min_entries_per_buffer=config.min_entries_per_buffer,
        audit_enabled=config.audit_enabled,
        triage_fullness_threshold=config.triage_fullness_threshold,
        triage_base_score=config.triage_base_score,
    )
