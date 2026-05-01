"""AD-455: Input validator — rate / payload / content policy gate."""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from probos.events import EventType
from probos.security.threat_detector import ThreatDetector, ThreatSignal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    reason: str = ""
    threats: tuple[ThreatSignal, ...] = ()


class InputValidator:
    """Per-source rate + size + content policy gate.

    Stateful in-memory. Source = stable identifier (DID, IP, agent_id).
    """

    def __init__(
        self,
        *,
        threat_detector: ThreatDetector,
        emit_event: Any | None = None,
        max_payload_bytes: int = 64 * 1024,
        rate_window_seconds: float = 60.0,
        rate_max_requests: int = 60,
        max_threat_severity: float = 0.80,
    ) -> None:
        self._threat = threat_detector
        self._emit_event = emit_event
        self._max_payload = max_payload_bytes
        self._window = rate_window_seconds
        self._rate_max = rate_max_requests
        self._max_threat_severity = max_threat_severity
        self._history: dict[str, deque[float]] = {}

    def check(self, *, source: str, payload: str) -> ValidationResult:
        if len(payload.encode("utf-8")) > self._max_payload:
            return self._reject(source, "payload_too_large")

        now = time.time()
        hist = self._history.setdefault(source, deque())
        while hist and now - hist[0] > self._window:
            hist.popleft()
        if len(hist) >= self._rate_max:
            return self._reject(source, "rate_limit")
        hist.append(now)

        threats = self._threat.scan(payload, source=source)
        max_sev = max((t.severity for t in threats), default=0.0)
        if max_sev >= self._max_threat_severity:
            return self._reject(source, f"content_policy:{max_sev:.2f}", tuple(threats))

        return ValidationResult(accepted=True, threats=tuple(threats))

    def _reject(
        self,
        source: str,
        reason: str,
        threats: tuple[ThreatSignal, ...] = (),
    ) -> ValidationResult:
        if self._emit_event:
            try:
                self._emit_event(
                    EventType.SECURITY_INPUT_REJECTED,
                    {"source": source, "reason": reason},
                )
            except Exception:
                logger.warning("AD-455: SECURITY_INPUT_REJECTED emit failed", exc_info=True)
        return ValidationResult(accepted=False, reason=reason, threats=threats)
