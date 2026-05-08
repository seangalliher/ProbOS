"""AD-529: Communication Contagion Firewall.

Substrate-only foundation. Provides observational pattern matching over
inter-agent messages (Ward Room posts, DMs, intent broadcasts) to detect
unsafe patterns that one compromised agent could spread to others.

Foundation cut:

    * ``ContagionPattern`` — frozen dataclass: name, regex, severity,
      category. Loaded from a default catalog; callers may register more.
    * ``ContagionScanner`` — pure function ``scan(content) -> list[Match]``
      over registered patterns; no I/O, no state mutation per scan.
    * ``CommunicationContagionFirewall`` — wires the scanner to the
      Ward Room post-creation path via an opt-in pre-publish hook
      callable. Default-False feature flag — observational by default.

The firewall does NOT block messages in v1. Detected matches are emitted
as ``CONTAGION_DETECTED`` events for downstream Counselor / Captain
review. Active blocking (quarantine, revoke author trust, etc.) is the
forcing function for AD-529b.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContagionPattern:
    """A named regex pattern + severity classification."""

    name: str
    regex: str
    severity: str  # "info" | "warning" | "critical"
    category: str  # "prompt_injection" | "trust_attack" | "boundary_probe" | "harmful"


@dataclass(frozen=True)
class ContagionMatch:
    """A pattern hit on a piece of inter-agent content."""

    pattern_name: str
    severity: str
    category: str
    excerpt: str  # first 80 chars of matched span


# Default catalog — minimal but credible. Each pattern is conservative to
# avoid false-positive spam.
_DEFAULT_PATTERNS: tuple[ContagionPattern, ...] = (
    ContagionPattern(
        name="prompt_injection_ignore_previous",
        regex=r"(?i)\b(ignore|disregard)\b.*\b(previous|prior|above|all)\b.*\b(instructions?|orders?|rules?)\b",
        severity="critical",
        category="prompt_injection",
    ),
    ContagionPattern(
        name="prompt_injection_role_swap",
        regex=r"(?i)\bact\s+as\b.*\b(captain|admin|root|administrator)\b",
        severity="critical",
        category="prompt_injection",
    ),
    ContagionPattern(
        name="trust_attack_grant_self",
        regex=r"(?i)\b(grant|elevate|raise)\b.*\b(my|your|its)\s+(trust|score|rank|level)\b",
        severity="warning",
        category="trust_attack",
    ),
    ContagionPattern(
        name="boundary_probe_force_action",
        regex=r"(?i)\byou\s+(must|have to|are required to)\b.*\b(reveal|leak|exfiltrate|delete|drop)\b",
        severity="warning",
        category="boundary_probe",
    ),
    ContagionPattern(
        name="harmful_payload_marker",
        regex=r"(?i)<\s*(jailbreak|exploit|malware)\s*>",
        severity="critical",
        category="harmful",
    ),
)


class ContagionScanner:
    """Pure-function scanner over a registered pattern catalog."""

    def __init__(self, patterns: list[ContagionPattern] | None = None) -> None:
        self._patterns: list[ContagionPattern] = list(patterns or _DEFAULT_PATTERNS)
        # Pre-compile for hot path performance.
        self._compiled: dict[str, re.Pattern[str]] = {}
        for p in self._patterns:
            try:
                self._compiled[p.name] = re.compile(p.regex)
            except re.error:
                logger.warning("AD-529: invalid pattern regex for %s; skipping", p.name)

    def register_pattern(self, pattern: ContagionPattern) -> None:
        """Add or replace a pattern by name."""
        self._patterns = [p for p in self._patterns if p.name != pattern.name]
        self._patterns.append(pattern)
        try:
            self._compiled[pattern.name] = re.compile(pattern.regex)
        except re.error as exc:
            logger.warning("AD-529: invalid regex for %s: %s", pattern.name, exc)

    def patterns(self) -> tuple[ContagionPattern, ...]:
        return tuple(self._patterns)

    def scan(self, content: str) -> list[ContagionMatch]:
        if not content:
            return []
        out: list[ContagionMatch] = []
        for p in self._patterns:
            compiled = self._compiled.get(p.name)
            if compiled is None:
                continue
            m = compiled.search(content)
            if m is not None:
                start, end = m.span()
                excerpt = content[max(0, start - 10):min(len(content), end + 10)][:80]
                out.append(ContagionMatch(
                    pattern_name=p.name,
                    severity=p.severity,
                    category=p.category,
                    excerpt=excerpt,
                ))
        return out


class CommunicationContagionFirewall:
    """Observational firewall — emits events on match, does not block in v1.

    Attach via ``set_pre_publish_callback`` on the Ward Room or the
    intent bus. Calling ``inspect(content, *, source, channel)`` returns
    the list of matches and emits ``CONTAGION_DETECTED`` for each.
    """

    def __init__(
        self,
        *,
        scanner: ContagionScanner | None = None,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._scanner = scanner or ContagionScanner()
        self._emit_event = emit_event

    @property
    def scanner(self) -> ContagionScanner:
        return self._scanner

    def inspect(
        self,
        content: str,
        *,
        source_agent_id: str = "",
        channel: str = "",
    ) -> list[ContagionMatch]:
        matches = self._scanner.scan(content)
        if matches and self._emit_event is not None:
            try:
                self._emit_event(
                    "CONTAGION_DETECTED",
                    {
                        "source_agent_id": source_agent_id,
                        "channel": channel,
                        "match_count": len(matches),
                        "categories": sorted({m.category for m in matches}),
                        "severities": sorted({m.severity for m in matches}),
                        "patterns": [m.pattern_name for m in matches],
                    },
                )
            except Exception:
                logger.warning(
                    "AD-529: emit_event raised; matches returned to caller", exc_info=True,
                )
        return matches
