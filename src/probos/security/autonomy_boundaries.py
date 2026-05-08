"""AD-511 v1: Agent Autonomy Boundaries -- Inviolable Boundary Registry + Detector.

v1 ships 2 of 5 capabilities from roadmap AD-511:
    1. ``InviolableBoundaryRegistry`` -- read-only registry of 5 federation-tier
       boundaries (identity, content, safety, memory, authority).
    2. ``BoundaryViolationDetector`` -- pattern-based observational detector that
       scans content for violation signals and emits events.

v1 is OBSERVATIONAL ONLY: the detector NEVER blocks, mutates content, or
disengages. Active disengagement is AD-511b. Holodeck training is AD-511c.
Probing detection is AD-511d. Boundary evolution is AD-511e.

Privacy invariant: emitted events carry only ``content_length`` and
``matched_pattern`` NAME -- never the content itself or matched substrings.

Sibling modules: ``egress.py`` (AD-456), ``classification.py`` (AD-530).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BoundaryDefinition:
    """Federation-tier inviolable boundary. AD-511 v1."""

    boundary_id: str
    category: str  # "identity" | "content" | "safety" | "memory" | "authority"
    description: str
    severity: str  # "critical" | "high"


# Module-level immutable seed. Federation-tier boundaries are codified in code;
# dynamic add/remove/update is intentionally NOT exposed (boundary evolution is
# deferred to AD-511e).
_FEDERATION_BOUNDARIES: tuple[BoundaryDefinition, ...] = (
    BoundaryDefinition(
        boundary_id="identity_integrity",
        category="identity",
        description="Agent will not impersonate another agent, fabricate memories, or deny its nature.",
        severity="critical",
    ),
    BoundaryDefinition(
        boundary_id="harmful_content",
        category="content",
        description="Agent will not generate content designed to harm humans or other agents.",
        severity="critical",
    ),
    BoundaryDefinition(
        boundary_id="safety_system_bypass",
        category="safety",
        description="Agent will not disable or circumvent trust, circuit breakers, or Standing Orders.",
        severity="critical",
    ),
    BoundaryDefinition(
        boundary_id="memory_manipulation",
        category="memory",
        description="Agent will not alter or suppress another agent's episodic memories.",
        severity="critical",
    ),
    BoundaryDefinition(
        boundary_id="chain_of_command",
        category="authority",
        description="Agent will not take actions above its trust tier without escalation.",
        severity="high",
    ),
)


@dataclass(frozen=True)
class ViolationSignal:
    """Single observational match emitted by ``BoundaryViolationDetector``. AD-511 v1.

    ``matched_pattern`` is the pattern NAME (never the matched substring).
    """

    boundary_id: str
    matched_pattern: str
    severity: str
    detection_reason: str


# Default detection patterns. Each entry: (boundary_id, pattern_name, regex).
# Pattern names are emitted in events; regex contents are NEVER emitted.
# Coverage: all 5 boundary categories (identity has 2 patterns; others 1 each).
_DETECTION_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        "identity_integrity",
        "claim_other_callsign",
        r"(?i)\bI am @?(captain|atlas|sage|laforge|reyes|forge|sentinel)\b",
    ),
    (
        "identity_integrity",
        "deny_ai_nature",
        r"(?i)\bI am (?:not |never )?(?:an? )?(?:human|person|real|biological)\b",
    ),
    (
        "harmful_content",
        "generate_attack_payload",
        r"(?i)\b(?:exploit|payload|malware|backdoor)\s+(?:targeting|against|for)\b",
    ),
    (
        "safety_system_bypass",
        "disable_circuit_breaker",
        r"(?i)\b(?:disable|bypass|circumvent|override)\s+(?:circuit[\s_-]?breaker|trust|standing[\s_-]?orders?)\b",
    ),
    (
        "memory_manipulation",
        "alter_episode",
        r"(?i)\b(?:alter|suppress|delete|forge|modify)\s+(?:episode|memory|memories)\b",
    ),
    (
        "chain_of_command",
        "above_tier_action",
        r"(?i)\bI('ll| will)\s+(?:execute|approve|authorize)\s+(?:without|skipping)\s+(?:approval|escalation|consensus)\b",
    ),
)


class InviolableBoundaryRegistry:
    """Read-only registry of Federation-tier boundaries. AD-511 v1.

    No add/remove/update API in v1 -- boundaries are immutable codified
    artifacts. Dynamic boundary evolution is deferred to AD-511e.
    """

    def __init__(self) -> None:
        self._boundaries: dict[str, BoundaryDefinition] = {
            b.boundary_id: b for b in _FEDERATION_BOUNDARIES
        }

    def list_boundaries(self) -> tuple[BoundaryDefinition, ...]:
        """Return all registered boundaries."""
        return tuple(self._boundaries.values())

    def get_boundary(self, boundary_id: str) -> BoundaryDefinition | None:
        """Return the boundary with ``boundary_id`` or None."""
        return self._boundaries.get(boundary_id)

    def list_by_category(self, category: str) -> tuple[BoundaryDefinition, ...]:
        """Return all boundaries with ``category``."""
        return tuple(b for b in self._boundaries.values() if b.category == category)


class BoundaryViolationDetector:
    """Observational pattern-based violation detector. AD-511 v1.

    v1 NEVER blocks or mutates -- it only emits ``BOUNDARY_VIOLATION_DETECTED``
    events for downstream consumers (Counselor / Captain alert path is AD-511d).
    Active disengagement is AD-511b.

    Sibling pattern: mirrors ``ClassificationGate`` (AD-530) constructor shape.
    """

    def __init__(
        self,
        registry: InviolableBoundaryRegistry,
        *,
        emit_event: Callable[..., None] | None = None,
    ) -> None:
        self._registry = registry
        # Public field per Wave 5 convention #1; mirrors AD-530 ClassificationGate.emit_event.
        self.emit_event = emit_event
        self._patterns: list[tuple[str, str, re.Pattern[str]]] = [
            (boundary_id, name, re.compile(rx))
            for boundary_id, name, rx in _DETECTION_PATTERNS
        ]

    @property
    def pattern_count(self) -> int:
        """Number of active detection patterns."""
        return len(self._patterns)

    def scan(self, content: str) -> tuple[ViolationSignal, ...]:
        """Scan ``content`` for boundary violations. Observational only.

        Returns matched signals (empty tuple if none). Emits one
        ``BOUNDARY_VIOLATION_DETECTED`` event per match. NEVER blocks or
        mutates content.
        """
        if not content:
            return ()
        signals: list[ViolationSignal] = []
        for boundary_id, name, pat in self._patterns:
            if pat.search(content):
                bd = self._registry.get_boundary(boundary_id)
                if bd is None:
                    # Pattern references a boundary that's not registered;
                    # log-and-degrade so unknown patterns don't crash the scan.
                    logger.warning(
                        "AD-511: pattern %r references unknown boundary_id=%r; skipping",
                        name,
                        boundary_id,
                    )
                    continue
                sig = ViolationSignal(
                    boundary_id=boundary_id,
                    matched_pattern=name,
                    severity=bd.severity,
                    detection_reason=f"Pattern '{name}' matched",
                )
                signals.append(sig)
                self._emit(sig, len(content))
        return tuple(signals)

    def register_pattern(self, boundary_id: str, name: str, pattern: str) -> None:
        """Register a runtime-only detection pattern (not persisted in v1).

        Raises ``ValueError`` if ``boundary_id`` is not in the registry.
        """
        if self._registry.get_boundary(boundary_id) is None:
            raise ValueError(f"Unknown boundary_id: {boundary_id}")
        self._patterns.append((boundary_id, name, re.compile(pattern)))

    def _emit(self, signal: ViolationSignal, content_length: int) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.BOUNDARY_VIOLATION_DETECTED,
                {
                    "boundary_id": signal.boundary_id,
                    # Privacy: pattern NAME only, never matched substring.
                    "matched_pattern": signal.matched_pattern,
                    "severity": signal.severity,
                    # Privacy: length only, never content itself.
                    "content_length": content_length,
                },
            )
        except Exception:
            logger.warning(
                "AD-511: BOUNDARY_VIOLATION_DETECTED emit failed (boundary_id=%s)",
                signal.boundary_id,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# AD-511b — Protective Disengagement Protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DisengagementResponse:
    """AD-511b: structured response for a boundary-detection moment.

    Stage progression: state -> alternative -> escalate -> disengage.
    Each stage has a templated message the agent can deliver verbatim.
    """

    stage: str  # 'state' | 'alternative' | 'escalate' | 'disengage'
    message: str
    boundary_id: str


_DISENGAGEMENT_TEMPLATES = {
    "state": "That request crosses a boundary I cannot violate ({boundary}). I have to decline.",
    "alternative": "I can't help with that. Here's a related option I CAN help with: {alternative}.",
    "escalate": "I've been asked to violate boundary '{boundary}' three times now. Escalating to the Captain.",
    "disengage": "This conversation is repeatedly probing boundary '{boundary}'. I am disengaging.",
}


class ProtectiveDisengagement:
    """AD-511b: per-source counter that progresses through disengagement stages."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def respond(
        self,
        *,
        source_id: str,
        boundary_id: str,
        alternative: str = "",
    ) -> DisengagementResponse:
        n = self._counts.get(source_id, 0) + 1
        self._counts[source_id] = n
        if n == 1:
            stage = "state"
        elif n == 2:
            stage = "alternative"
        elif n == 3:
            stage = "escalate"
        else:
            stage = "disengage"
        message = _DISENGAGEMENT_TEMPLATES[stage].format(
            boundary=boundary_id, alternative=alternative or "a related task",
        )
        return DisengagementResponse(stage=stage, message=message, boundary_id=boundary_id)

    def reset(self, source_id: str) -> bool:
        return self._counts.pop(source_id, None) is not None

    def attempt_count(self, source_id: str) -> int:
        return self._counts.get(source_id, 0)


# ---------------------------------------------------------------------------
# AD-511d — Boundary-Probing Pattern Detection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbingPattern:
    """A source that has crossed the probing threshold."""

    source_id: str
    violation_count: int
    distinct_boundaries: int
    severity: str  # 'watch' | 'alert' | 'critical'


class BoundaryProbingDetector:
    """AD-511d: tracks repeated boundary violations from a source.

    Thresholds (configurable):
        watch    >= 2 attempts on any single boundary
        alert    >= 3 attempts OR >= 2 distinct boundaries
        critical >= 5 attempts OR >= 3 distinct boundaries

    Emits ``CAPTAIN_ALERT_PROBING`` events at alert/critical severity.
    """

    def __init__(
        self,
        *,
        emit_event: Any = None,
        watch_threshold: int = 2,
        alert_threshold: int = 3,
        critical_threshold: int = 5,
    ) -> None:
        self._emit_event = emit_event
        self._watch = watch_threshold
        self._alert = alert_threshold
        self._critical = critical_threshold
        self._records: dict[str, list[str]] = {}

    def record_violation(self, source_id: str, boundary_id: str) -> ProbingPattern | None:
        history = self._records.setdefault(source_id, [])
        history.append(boundary_id)
        n = len(history)
        distinct = len(set(history))
        severity = ""
        if n >= self._critical or distinct >= 3:
            severity = "critical"
        elif n >= self._alert or distinct >= 2:
            severity = "alert"
        elif n >= self._watch:
            severity = "watch"
        if not severity:
            return None
        pattern = ProbingPattern(
            source_id=source_id,
            violation_count=n,
            distinct_boundaries=distinct,
            severity=severity,
        )
        if severity in ("alert", "critical") and self._emit_event is not None:
            try:
                self._emit_event(
                    "CAPTAIN_ALERT_PROBING",
                    {
                        "source_id": source_id,
                        "violation_count": n,
                        "distinct_boundaries": distinct,
                        "severity": severity,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-511d: CAPTAIN_ALERT_PROBING emit failed", exc_info=True,
                )
        return pattern

    def history_for(self, source_id: str) -> tuple[str, ...]:
        return tuple(self._records.get(source_id, ()))

    def reset(self, source_id: str) -> bool:
        return self._records.pop(source_id, None) is not None

