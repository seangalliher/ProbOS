"""AD-564: Quality-triggered forced consolidation."""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.config import QualityTriggerConfig

logger = logging.getLogger(__name__)


class QualityConsolidationTrigger:
    """Decides when notebook quality should force consolidation."""

    def __init__(self, config: QualityTriggerConfig, emit_event_fn: Any = None) -> None:
        self._config = config
        self._emit_event_fn = emit_event_fn
        self._last_trigger_time: float = 0.0
        self._forced_today: int = 0
        self._day_start: float = time.time()

    def check_and_trigger(self, snapshot: Any) -> bool:
        """Return True when snapshot quality should force consolidation."""
        if not self._config.enabled:
            return False

        should_trigger, reason = self._should_trigger(snapshot)
        if not should_trigger:
            return False
        if not self._cooldown_ok():
            return False
        if not self._daily_limit_ok():
            return False

        self._last_trigger_time = time.time()
        self._forced_today += 1
        logger.info(
            "AD-564: Forced notebook consolidation triggered because %s; dream cycle will run ship-wide maintenance",
            reason,
        )
        if self._emit_event_fn:
            self._emit_event_fn("forced_consolidation_triggered", {
                "reason": reason,
                "quality_score": snapshot.system_quality_score,
                "stale_rate": snapshot.stale_entry_rate,
                "repetition_rate": snapshot.repetition_alert_rate,
            })
        return True

    def _should_trigger(self, snapshot: Any) -> tuple[bool, str]:
        quality_score = float(snapshot.system_quality_score)
        stale_rate = float(snapshot.stale_entry_rate)
        repetition_rate = float(snapshot.repetition_alert_rate)

        if quality_score < self._config.min_quality_threshold:
            return True, f"quality_score {quality_score:.3f} < {self._config.min_quality_threshold}"
        if stale_rate > self._config.max_stale_rate:
            return True, f"stale_rate {stale_rate:.3f} > {self._config.max_stale_rate}"
        if repetition_rate > self._config.max_repetition_rate:
            return True, f"repetition_rate {repetition_rate:.3f} > {self._config.max_repetition_rate}"
        return False, ""

    def _cooldown_ok(self) -> bool:
        return time.time() - self._last_trigger_time >= self._config.cooldown_seconds

    def _daily_limit_ok(self) -> bool:
        now = time.time()
        if now - self._day_start >= 86400.0:
            self._forced_today = 0
            self._day_start = now
        return self._forced_today < self._config.max_forced_per_day