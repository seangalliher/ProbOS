"""AD-670: Working Memory Metabolism — active lifecycle management.

Four operations replace passive FIFO eviction:
  DECAY  — exponential time-weighted salience reduction
  AUDIT  — flag contradictory entries in same buffer
  FORGET — remove entries whose decayed salience falls below threshold
  TRIAGE — score incoming entries for buffer admission
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass

from probos.cognitive.agent_working_memory import WorkingMemoryEntry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuditFlag:
    """A flagged pair of potentially contradictory entries."""

    entry_a_content: str
    entry_b_content: str
    buffer_name: str
    reason: str


@dataclass(frozen=True)
class MetabolismReport:
    """Summary of a single metabolism cycle."""

    decayed_count: int
    forgotten_count: int
    audit_flags: list[AuditFlag]
    cycle_duration_ms: float


class MemoryMetabolism:
    """Stateless working memory lifecycle manager."""

    def __init__(
        self,
        *,
        decay_half_life_seconds: float = 3600.0,
        forget_threshold: float = 0.05,
        min_entries_per_buffer: int = 2,
        audit_enabled: bool = True,
        triage_fullness_threshold: float = 0.8,
        triage_base_score: float = 0.3,
    ) -> None:
        if decay_half_life_seconds <= 0:
            raise ValueError("decay_half_life_seconds must be positive")
        if not (0.0 <= forget_threshold <= 1.0):
            raise ValueError("forget_threshold must be between 0.0 and 1.0")
        if min_entries_per_buffer < 0:
            raise ValueError("min_entries_per_buffer must be non-negative")

        self._decay_half_life = decay_half_life_seconds
        self._forget_threshold = forget_threshold
        self._min_entries = min_entries_per_buffer
        self._audit_enabled = audit_enabled
        self._triage_fullness_threshold = triage_fullness_threshold
        self._triage_base_score = triage_base_score

    def decay(self, buffer: deque[WorkingMemoryEntry], now: float | None = None) -> int:
        """Apply exponential decay to all entries in a buffer."""
        now = now or time.time()
        count = 0
        for entry in buffer:
            age = now - entry.timestamp
            score = math.exp(-age * math.log(2) / self._decay_half_life)
            entry.metadata["_decay_score"] = round(score, 6)
            count += 1
        return count

    def forget(self, buffer: deque[WorkingMemoryEntry]) -> int:
        """Remove entries whose decay score is below the forget threshold."""
        if len(buffer) <= self._min_entries:
            return 0

        scored = [
            (entry, entry.metadata.get("_decay_score", 1.0))
            for entry in buffer
        ]
        scored.sort(key=lambda item: item[1], reverse=True)

        keep: list[WorkingMemoryEntry] = []
        remove_count = 0
        for index, (entry, score) in enumerate(scored):
            if index < self._min_entries or score >= self._forget_threshold:
                keep.append(entry)
            else:
                remove_count += 1
                logger.debug(
                    "AD-670 FORGET: removing entry (score=%.4f, age=%.0fs): %.60s...",
                    score,
                    entry.age_seconds(),
                    entry.content,
                )

        if remove_count > 0:
            keep_ids = {id(entry) for entry in keep}
            surviving = [entry for entry in buffer if id(entry) in keep_ids]
            buffer.clear()
            buffer.extend(surviving)

        return remove_count

    def audit(
        self,
        buffer: deque[WorkingMemoryEntry],
        buffer_name: str,
    ) -> list[AuditFlag]:
        """Scan for potentially contradictory entries in the same buffer."""
        if not self._audit_enabled:
            return []

        negation_words = frozenset({
            "not", "no", "never", "none", "nothing", "neither",
            "nobody", "nowhere", "isn't", "aren't", "wasn't",
            "weren't", "won't", "don't", "doesn't", "didn't",
            "can't", "couldn't", "shouldn't", "wouldn't",
            "unable", "failed", "failure", "stopped", "declined",
        })
        flags: list[AuditFlag] = []
        entries = list(buffer)

        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                first = entries[i]
                second = entries[j]
                if first.source_pathway != second.source_pathway:
                    continue
                if abs(first.timestamp - second.timestamp) > 300:
                    continue

                first_words = set(first.content.lower().split())
                second_words = set(second.content.lower().split())
                first_negation = first_words & negation_words
                second_negation = second_words & negation_words
                if bool(first_negation) == bool(second_negation):
                    continue

                content_overlap = {
                    word for word in (first_words & second_words)
                    if len(word) > 3 and word not in negation_words
                }
                if content_overlap:
                    flags.append(AuditFlag(
                        entry_a_content=first.content[:100],
                        entry_b_content=second.content[:100],
                        buffer_name=buffer_name,
                        reason=(
                            "Potential contradiction: shared topics "
                            f"{content_overlap}, opposing sentiment"
                        ),
                    ))

        return flags

    def triage(
        self,
        entry: WorkingMemoryEntry,
        buffer: deque[WorkingMemoryEntry],
    ) -> bool:
        """Score an incoming entry for buffer admission."""
        if buffer.maxlen is None or buffer.maxlen == 0:
            return True

        if not entry.content.strip():
            return False

        fullness = len(buffer) / buffer.maxlen
        score = 1.0
        if fullness >= self._triage_fullness_threshold:
            overflow_ratio = (fullness - self._triage_fullness_threshold) / (
                1.0 - self._triage_fullness_threshold
            )
            required_score = self._triage_base_score + (
                (1.0 - self._triage_base_score) * overflow_ratio
            )
        else:
            required_score = self._triage_base_score

        if len(entry.content) < 20:
            score *= 0.5

        return score >= required_score

    def run_cycle(
        self,
        buffers: dict[str, deque[WorkingMemoryEntry]],
    ) -> MetabolismReport:
        """Execute DECAY, AUDIT, and FORGET across all buffers."""
        start = time.monotonic()
        now = time.time()
        total_decayed = 0
        total_forgotten = 0
        all_flags: list[AuditFlag] = []

        for name, buffer in buffers.items():
            if not buffer:
                continue
            total_decayed += self.decay(buffer, now=now)
            flags = self.audit(buffer, buffer_name=name)
            all_flags.extend(flags)
            total_forgotten += self.forget(buffer)

        elapsed_ms = (time.monotonic() - start) * 1000
        if total_forgotten > 0 or all_flags:
            logger.info(
                "AD-670 metabolism cycle complete: decayed=%d, forgotten=%d, "
                "audit_flags=%d, duration=%.1fms",
                total_decayed,
                total_forgotten,
                len(all_flags),
                elapsed_ms,
            )

        return MetabolismReport(
            decayed_count=total_decayed,
            forgotten_count=total_forgotten,
            audit_flags=all_flags,
            cycle_duration_ms=round(elapsed_ms, 2),
        )
