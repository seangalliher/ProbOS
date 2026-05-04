"""AD-530 v1: Information Classification Enforcement -- Disclosure Gate.

Observational gate at the communication boundary. Reuses the existing
``_CLASSIFICATION_LEVELS`` hierarchy from records_store.py (read-only).

Hierarchy (records_store.py:27): ``private`` (0) / ``department`` (1) /
``ship`` (2) / ``fleet`` (3). Higher index = BROADER access.

Disclosure rule: BLOCK when ``dst_lvl > src_lvl`` -- destination has broader
reach than the source classification permits. Direction is grounded in
records_store.py:841 (``if doc_class_level > scope_level: continue`` filters
out broader-than-scope docs).

v1 is OBSERVATIONAL: ``check_disclosure`` returns a ``DisclosureDecision``
and emits ``CLASSIFICATION_DISCLOSURE_BLOCKED`` on blocks. It NEVER mutates
outbound messages. Active enforcement (Ward Room, LLM prompt builder) is
deferred to AD-530d.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal

from probos.events import EventType
from probos.knowledge.records_store import _CLASSIFICATION_LEVELS

logger = logging.getLogger(__name__)


DisclosureReason = Literal[
    "ok",
    "destination_too_broad",
    "sensitive_pattern_matched",
]


@dataclass(frozen=True)
class DisclosureDecision:
    """Result of a classification disclosure check. AD-530 v1."""

    allowed: bool
    reason: DisclosureReason
    blocked_phrases: tuple[str, ...]  # pattern NAMES that triggered the block (never matched substrings)
    source_classification: str  # echoed for audit
    destination_clearance: str  # echoed for audit


# AD-530 v1 default sensitive-content patterns. Tightly scoped to known-high-signal
# shapes; the high-FP 32+ char alphanum heuristic (`api_key_like`) is INTENTIONALLY
# NOT in the default set (UUIDs, commit hashes, and opaque IDs collide with it).
# Callers that want it opt in via `register_pattern("api_key_like", r"\b[A-Za-z0-9_-]{32,}\b")`.
# Default-set revisit is AD-530e.
_DEFAULT_SENSITIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("captain_directive", r"\[CAPTAIN_DIRECTIVE\]"),
    # Matches the literal "private:" / "confidential:" prefix marker, NOT the classification key.
    ("restricted_prefix", r"\b(private|confidential):\s"),
    ("secret_format", r"(?i)\b(secret|api[_-]?key|password|token)\s*[:=]\s*\S+"),
)


class ClassificationGate:
    """v1 disclosure gate. Read-only check; no message mutation. AD-530 v1.

    Hierarchy semantics (see records_store.py:26-32, :716, :841):
      ``_CLASSIFICATION_LEVELS = {"private": 0, "department": 1, "ship": 2, "fleet": 3}``
      Higher index = BROADER access (more openly readable).

    Disclosure rule: BLOCK when ``dst_lvl > src_lvl`` -- destination has broader
    reach than source classification permits.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        emit_event: Callable[..., None] | None = None,
    ) -> None:
        self._runtime = runtime
        # Public field per Wave 5 convention #1; mirrors AD-456 EgressPolicy.emit_event.
        self.emit_event = emit_event
        self._patterns: list[tuple[str, re.Pattern[str]]] = [
            (name, re.compile(pat)) for name, pat in _DEFAULT_SENSITIVE_PATTERNS
        ]

    @property
    def patterns(self) -> tuple[tuple[str, re.Pattern[str]], ...]:
        """Public read-only view of the active pattern set (Wave 5 convention #1)."""
        return tuple(self._patterns)

    @property
    def pattern_count(self) -> int:
        """Number of active sensitive-content patterns."""
        return len(self._patterns)

    def check_disclosure(
        self,
        content: str,
        *,
        source_classification: str,
        destination_clearance: str,
    ) -> DisclosureDecision:
        """Check whether ``content`` may be disclosed at ``destination_clearance`` level.

        Args:
            content: The outbound message body.
            source_classification: Source data's classification label. One of the
                ``_CLASSIFICATION_LEVELS`` keys ("private", "department", "ship",
                "fleet"). Unknown / unspecified labels default to MOST RESTRICTIVE
                ("private", level 0) so unlabeled content cannot leak by mistake.
            destination_clearance: Destination's reach level (same hierarchy).
                Unknown / unspecified destinations default to BROADEST ("ship",
                level 2). Combined with the source default, an entirely
                unspecified pair is BLOCKED by hierarchy (private -> ship: 2 > 0).

        Returns:
            ``DisclosureDecision``. ``allowed=True`` when ``dst_lvl <= src_lvl`` AND
            no sensitive patterns matched.
        """
        # Higher index = broader access. Block when destination is broader than source allows.
        # Safe defaults: source unknown -> most restrictive (private=0); dest unknown -> broadest (ship=2).
        src_lvl = _CLASSIFICATION_LEVELS.get(
            source_classification, _CLASSIFICATION_LEVELS["private"]
        )
        dst_lvl = _CLASSIFICATION_LEVELS.get(
            destination_clearance, _CLASSIFICATION_LEVELS["ship"]
        )
        if dst_lvl > src_lvl:
            decision = DisclosureDecision(
                allowed=False,
                reason="destination_too_broad",
                blocked_phrases=(),
                source_classification=source_classification,
                destination_clearance=destination_clearance,
            )
            self._emit_blocked(content, decision)
            return decision

        # Pattern scan: skip when destination is the most-restrictive level ("private").
        # Patterns target sensitive-content disclosure to broader audiences; if the
        # destination is already private (level 0), there's no broader audience to leak to.
        matches: list[str] = []
        if dst_lvl > _CLASSIFICATION_LEVELS["private"]:
            for name, pat in self._patterns:
                if pat.search(content):
                    matches.append(name)
        if matches:
            decision = DisclosureDecision(
                allowed=False,
                reason="sensitive_pattern_matched",
                blocked_phrases=tuple(matches),
                source_classification=source_classification,
                destination_clearance=destination_clearance,
            )
            self._emit_blocked(content, decision)
            return decision

        return DisclosureDecision(
            allowed=True,
            reason="ok",
            blocked_phrases=(),
            source_classification=source_classification,
            destination_clearance=destination_clearance,
        )

    def register_pattern(self, name: str, pattern: str) -> None:
        """Add a sensitive-content pattern (runtime-only; not persisted in v1).

        Duplicate-name semantics: if ``name`` is already registered, the existing
        pattern is preserved and a warning is logged. Callers that need to
        replace a pattern should choose a fresh name (or wait for AD-530e's
        explicit replace API).
        """
        for existing_name, _ in self._patterns:
            if existing_name == name:
                logger.warning(
                    "AD-530: register_pattern skipped -- name %r already registered",
                    name,
                )
                return
        self._patterns.append((name, re.compile(pattern)))

    def _emit_blocked(self, content: str, decision: DisclosureDecision) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.CLASSIFICATION_DISCLOSURE_BLOCKED,
                {
                    "reason": decision.reason,
                    "source_classification": decision.source_classification,
                    "destination_clearance": decision.destination_clearance,
                    # Privacy: pattern NAMES only, never matched substrings.
                    "blocked_phrases": list(decision.blocked_phrases),
                    # Privacy: length only, never the content itself.
                    "content_length": len(content),
                },
            )
        except Exception:
            logger.warning(
                "AD-530: CLASSIFICATION_DISCLOSURE_BLOCKED emit failed (reason=%s)",
                decision.reason,
                exc_info=True,
            )
