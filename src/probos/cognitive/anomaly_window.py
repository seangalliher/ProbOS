"""AD-673: Automated anomaly window detection."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


class AnomalyWindowManager:
    """Tracks active anomaly windows and exposes episode stamping state."""

    def __init__(
        self,
        config: Any,
        emit_event_fn: Callable[[str, dict], None] | None = None,
        add_event_listener_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._active_window_id: str | None = None
        self._active_signal_type: str = ""
        self._active_details: str = ""
        self._opened_at: float = 0.0
        self._affected_count: int = 0
        self._config = config
        self._emit_event_fn = emit_event_fn
        self._add_event_listener_fn = add_event_listener_fn

    def open_window(self, signal_type: str, details: str = "") -> str:
        """Open an anomaly window or merge into the active one."""
        active_window = self.get_active_window()
        if active_window:
            self._affected_count += 1
            logger.info(
                "AD-673: Merged anomaly signal %s into active window %s; continuing existing window",
                signal_type,
                active_window,
            )
            return active_window

        window_id = f"aw-{uuid.uuid4().hex[:8]}"
        self._active_window_id = window_id
        self._active_signal_type = signal_type
        self._active_details = details
        self._opened_at = time.monotonic()
        self._affected_count = 0

        self._emit(
            EventType.ANOMALY_WINDOW_OPENED,
            {
                "window_id": window_id,
                "signal_type": signal_type,
                "details": details,
            },
        )
        logger.info(
            "AD-673: Opened anomaly window %s for %s; future episodes will be stamped",
            window_id,
            signal_type,
        )
        return window_id

    def close_window(self, window_id: str) -> None:
        """Close the active anomaly window if the ID matches."""
        if not self._active_window_id or window_id != self._active_window_id:
            logger.warning(
                "AD-673: Ignored close for anomaly window %s; active window is %s and state remains unchanged",
                window_id,
                self._active_window_id or "none",
            )
            return

        duration = time.monotonic() - self._opened_at
        signal_type = self._active_signal_type
        affected_count = self._affected_count
        self._emit(
            EventType.ANOMALY_WINDOW_CLOSED,
            {
                "window_id": window_id,
                "duration_seconds": duration,
                "affected_episodes": affected_count,
                "signal_type": signal_type,
            },
        )

        self._active_window_id = None
        self._active_signal_type = ""
        self._active_details = ""
        self._opened_at = 0.0
        self._affected_count = 0
        logger.info(
            "AD-673: Closed anomaly window %s after %.2fs with %d affected episodes",
            window_id,
            duration,
            affected_count,
        )

    def get_active_window(self) -> str | None:
        """Return the active window ID, auto-closing expired windows."""
        if not self._active_window_id:
            return None

        elapsed = time.monotonic() - self._opened_at
        if elapsed > self._config.max_window_duration_seconds:
            expired_window = self._active_window_id
            self.close_window(expired_window)
            return None

        return self._active_window_id

    def is_active(self) -> bool:
        """Return whether a non-expired anomaly window is active."""
        return self.get_active_window() is not None

    def tag_recent(self, window_id: str, lookback_seconds: float) -> int:
        """Retrospective tagging interface; mutation is deferred to a later AD."""
        logger.debug(
            "AD-673: Retrospective tagging requested for %s over %.1fs; deferred interface returns zero",
            window_id,
            lookback_seconds,
        )
        return 0

    def record_episode_stamped(self) -> None:
        """Record that an episode was stamped with the active window."""
        self._affected_count += 1

    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        if self._emit_event_fn is None:
            return
        try:
            self._emit_event_fn(event_type, data)
        except Exception:
            logger.debug(
                "AD-673: Failed to emit anomaly window event %s; window state remains authoritative",
                event_type.value,
                exc_info=True,
            )