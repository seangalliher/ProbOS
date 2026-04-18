"""AD-529: Communication Contagion Firewall.

Trust-based content scanning at the Ward Room posting boundary.
Detects fabrication signals (ungrounded hex IDs, phantom thread refs,
fabricated metrics) and labels flagged posts with ``[UNVERIFIED]``.
Zero LLM calls — all checks are deterministic.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)

# Reuse BF-204 hex-ID regex (evaluate.py:321)
_HEX_ID_RE = re.compile(r'\b[0-9a-f]{6,}\b', re.IGNORECASE)
# Phantom thread references
_PHANTOM_THREAD_RE = re.compile(
    r'thread\s+(?:[a-f0-9-]{6,}|#\d+)', re.IGNORECASE,
)
# Fabricated metrics: precise numeric claims with units
_FABRICATED_METRIC_RE = re.compile(
    r'\b\d+(?:\.\d+)?'                  # number
    r'\s*(?:ms|MHz|GHz|KB|MB|GB|TB|%|'  # units
    r'seconds?|minutes?|hours?|days?|'
    r'bytes?|packets?|requests?/s|ops/s|'
    r'baseline|spikes?)\b'
    r'|'
    r'[±]\s*\d+(?:\.\d+)?%',           # ±N.N%
    re.IGNORECASE,
)


@dataclass
class ScanResult:
    """Result of a deterministic content scan."""

    flagged: bool
    reasons: list[str]
    severity: str  # "none" | "low" | "medium" | "high"
    trust_score: float


@dataclass
class _FlagRecord:
    timestamp: float
    scan: ScanResult


class ContentFirewall:
    """Trust-gated deterministic content scanner for Ward Room posts.

    Injected into MessageStore and ThreadManager via ``set_content_firewall()``.
    Scans posts from agents below a trust threshold and labels flagged
    content with ``[UNVERIFIED — reasons]``.

    Parameters
    ----------
    trust_network:
        Object with ``get_score(agent_id) -> float``.
    emit_event_fn:
        ``(event_type: str, data: dict) -> None`` callback.
    config:
        ``FirewallConfig`` Pydantic model from ``config.py``.
    """

    def __init__(
        self,
        trust_network: Any,
        emit_event_fn: Callable[..., Any] | None = None,
        config: Any | None = None,
    ) -> None:
        self._trust_network = trust_network
        self._emit_event_fn = emit_event_fn

        # Import lazily to avoid circular imports at module level
        if config is None:
            from probos.config import FirewallConfig
            config = FirewallConfig()
        self._config = config

        # Per-agent flag history: agent_id → list of (timestamp, ScanResult)
        self._flag_history: dict[str, list[_FlagRecord]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_post(
        self,
        author_id: str,
        body: str,
        thread_context: str = "",
    ) -> ScanResult:
        """Synchronous deterministic content scan.  Zero LLM calls.

        High-trust agents pass through unscanned.
        """
        if not body or not body.strip():
            return ScanResult(
                flagged=False, reasons=[], severity="none", trust_score=0.0,
            )

        # Get trust score — degrade gracefully if unavailable
        trust = 0.5
        try:
            if self._trust_network:
                trust = self._trust_network.get_score(author_id)
        except Exception:
            logger.debug(
                "AD-529: Trust lookup failed for %s, using default", author_id[:8],
            )

        # High-trust agents pass unscanned
        if trust >= self._config.scan_trust_threshold:
            return ScanResult(
                flagged=False, reasons=[], severity="none", trust_score=trust,
            )

        reasons: list[str] = []

        # Check 1: Ungrounded hex IDs
        reasons.extend(self._check_hex_ids(body, thread_context))

        # Check 2: Phantom thread references
        reasons.extend(self._check_phantom_refs(body, thread_context))

        # Check 3: Fabricated metrics (only for very low trust)
        if trust < self._config.low_trust_threshold:
            reasons.extend(self._check_fabricated_metrics(body, thread_context))

        if not reasons:
            return ScanResult(
                flagged=False, reasons=[], severity="none", trust_score=trust,
            )

        severity = (
            "high" if len(reasons) >= 3
            else "medium" if len(reasons) >= 2
            else "low"
        )
        return ScanResult(
            flagged=True, reasons=reasons, severity=severity, trust_score=trust,
        )

    def record_flag(self, agent_id: str, scan: ScanResult) -> None:
        """Track flag and emit events.  Escalate on repeated flags."""
        now = time.time()
        if agent_id not in self._flag_history:
            self._flag_history[agent_id] = []

        self._flag_history[agent_id].append(_FlagRecord(now, scan))

        # Prune old flags outside window
        cutoff = now - self._config.flag_window_seconds
        self._flag_history[agent_id] = [
            r for r in self._flag_history[agent_id] if r.timestamp > cutoff
        ]

        count = len(self._flag_history[agent_id])

        # Emit flag event
        if self._emit_event_fn:
            self._emit_event_fn(
                EventType.CONTENT_CONTAGION_FLAGGED.value,
                {
                    "agent_id": agent_id,
                    "reasons": scan.reasons,
                    "severity": scan.severity,
                    "trust_score": scan.trust_score,
                    "flags_in_window": count,
                },
            )

        # Bridge alert on high severity
        if scan.severity == "high" and self._emit_event_fn:
            self._emit_bridge_alert(
                agent_id=agent_id,
                severity="ADVISORY",
                title=f"Content firewall: agent flagged for unverified claims",
                detail=(
                    f"Reasons: {', '.join(scan.reasons)}. "
                    f"Trust: {scan.trust_score:.2f}. Flags in window: {count}."
                ),
                dedup_key=f"contagion:{agent_id}:{scan.reasons[0]}",
            )

        # Escalate on repeated flags
        if count >= self._config.quarantine_threshold:
            all_reasons = [
                r
                for rec in self._flag_history[agent_id]
                for r in rec.scan.reasons
            ]
            if self._emit_event_fn:
                self._emit_event_fn(
                    EventType.CONTENT_QUARANTINE_RECOMMENDED.value,
                    {
                        "agent_id": agent_id,
                        "flags_in_window": count,
                        "window_seconds": self._config.flag_window_seconds,
                        "reasons": all_reasons,
                    },
                )
                # Bridge alert for quarantine recommendation
                self._emit_bridge_alert(
                    agent_id=agent_id,
                    severity="ALERT",
                    title=f"Content quarantine recommended",
                    detail=(
                        f"{count} flags in {self._config.flag_window_seconds}s window. "
                        f"Reasons: {', '.join(set(all_reasons))}."
                    ),
                    dedup_key=f"quarantine:{agent_id}",
                )

    # ------------------------------------------------------------------
    # Deterministic checks
    # ------------------------------------------------------------------

    def _check_hex_ids(self, body: str, thread_context: str) -> list[str]:
        """Check 1: Ungrounded hex IDs (reuse BF-204 pattern)."""
        hex_ids = _HEX_ID_RE.findall(body.lower())
        if len(hex_ids) < self._config.hex_id_threshold:
            return []

        context_lower = thread_context.lower()
        ungrounded = [h for h in hex_ids if h not in context_lower]

        if len(ungrounded) >= self._config.hex_id_threshold:
            return ["ungrounded_hex_ids"]
        return []

    def _check_phantom_refs(self, body: str, thread_context: str) -> list[str]:
        """Check 2: References to threads/IDs not in context."""
        matches = _PHANTOM_THREAD_RE.findall(body)
        if not matches:
            return []

        context_lower = thread_context.lower()
        phantoms = [m for m in matches if m.lower().strip() not in context_lower]

        if phantoms:
            return ["phantom_thread_ref"]
        return []

    def _check_fabricated_metrics(
        self, body: str, thread_context: str,
    ) -> list[str]:
        """Check 3: Suspiciously precise quantitative claims with no source.

        Only runs for agents with trust < low_trust_threshold (0.45).
        """
        metrics = _FABRICATED_METRIC_RE.findall(body)
        if len(metrics) < self._config.fabricated_metrics_threshold:
            return []

        # If metrics also appear in thread context, they're grounded
        context_lower = thread_context.lower()
        ungrounded = [
            m for m in metrics if m.lower() not in context_lower
        ]

        if len(ungrounded) >= self._config.fabricated_metrics_threshold:
            return ["fabricated_metrics"]
        return []

    # ------------------------------------------------------------------
    # Bridge alert helper
    # ------------------------------------------------------------------

    def _emit_bridge_alert(
        self,
        *,
        agent_id: str,
        severity: str,
        title: str,
        detail: str,
        dedup_key: str,
    ) -> None:
        """Emit a bridge alert via event bus (BridgeAlertService picks it up)."""
        import uuid as _uuid

        from probos.bridge_alerts import AlertSeverity, BridgeAlert

        sev = AlertSeverity.ALERT if severity == "ALERT" else AlertSeverity.ADVISORY
        alert = BridgeAlert(
            id=str(_uuid.uuid4()),
            severity=sev,
            source="content_firewall",
            alert_type="content_contagion",
            title=title,
            detail=detail,
            department=None,
            dedup_key=dedup_key,
            related_agent_id=agent_id,
        )

        # Emit as event so BridgeAlertService + WardRoomRouter can deliver
        self._emit_event_fn(
            EventType.BRIDGE_ALERT.value
            if hasattr(EventType, "BRIDGE_ALERT")
            else "bridge_alert",
            {
                "alert": alert,
                "severity": alert.severity.value,
                "source": alert.source,
                "title": alert.title,
                "detail": alert.detail,
                "dedup_key": alert.dedup_key,
                "agent_id": agent_id,
            },
        )
