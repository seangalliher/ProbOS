"""AD-444: Knowledge confidence scoring."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from probos.config import ConfidenceConfig


@dataclass
class ConfidenceEntry:
    """Confidence state for one Ship's Records entry."""

    entry_path: str
    confidence: float = 0.5
    confirmations: int = 0
    contradictions: int = 0
    last_updated: float = field(default_factory=time.time)


class ConfidenceTracker:
    """In-memory confidence tracker for Ship's Records entries."""

    def __init__(self, config: ConfidenceConfig) -> None:
        self._config = config
        self._entries: dict[str, ConfidenceEntry] = {}

    def initialize_entry(self, entry_path: str) -> float:
        """Create a tracked entry if needed and return its confidence."""
        if not self._config.enabled:
            return self._config.default_confidence
        if entry_path not in self._entries:
            self._entries[entry_path] = ConfidenceEntry(
                entry_path=entry_path,
                confidence=self._config.default_confidence,
            )
        return self._entries[entry_path].confidence

    def get_confidence(self, entry_path: str) -> float:
        """Return the current confidence for an entry."""
        if not self._config.enabled:
            return self._config.default_confidence
        entry = self._entries.get(entry_path)
        if entry is None:
            return self._config.default_confidence
        return entry.confidence

    def confirm(self, entry_path: str) -> float:
        """Confirm an entry, increasing confidence up to 1.0."""
        if not self._config.enabled:
            return self._config.default_confidence
        self.initialize_entry(entry_path)
        entry = self._entries[entry_path]
        entry.confidence = min(1.0, entry.confidence + self._config.confirm_delta)
        entry.confirmations += 1
        entry.last_updated = time.time()
        return entry.confidence

    def contradict(self, entry_path: str) -> float:
        """Contradict an entry, decreasing confidence down to 0.0."""
        if not self._config.enabled:
            return self._config.default_confidence
        self.initialize_entry(entry_path)
        entry = self._entries[entry_path]
        entry.confidence = max(0.0, entry.confidence - self._config.contradict_delta)
        entry.contradictions += 1
        entry.last_updated = time.time()
        return entry.confidence

    def auto_supersede_check(self, entry_path: str) -> bool:
        """Return True when confidence falls below auto-supersede threshold."""
        if not self._config.enabled:
            return False
        return self.get_confidence(entry_path) < self._config.auto_supersede_threshold

    def get_presentation_tier(self, entry_path: str) -> str:
        """Return the presentation tier for an entry's current confidence."""
        if not self._config.enabled:
            return "with_caveat"
        confidence = self.get_confidence(entry_path)
        if confidence >= self._config.auto_apply_threshold:
            return "auto_apply"
        if confidence < self._config.suppress_threshold:
            return "suppress"
        return "with_caveat"

    def get_all_entries(self) -> dict[str, ConfidenceEntry]:
        """Return a shallow copy of tracked confidence entries."""
        if not self._config.enabled:
            return {}
        return dict(self._entries)