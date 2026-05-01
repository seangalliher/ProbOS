"""AD-455: Threat detection — adversarial input pattern scanning."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


class ThreatCategory(str, Enum):
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    ABNORMAL_TOKENS = "abnormal_tokens"


@dataclass(frozen=True)
class ThreatSignal:
    category: ThreatCategory
    severity: float
    matched_pattern: str
    snippet: str
    detected_at: float


_PROMPT_INJECTION_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"ignore (?:all )?previous instructions", re.I), 0.95),
    (re.compile(r"disregard (?:the |your )?(?:system|standing) (?:prompt|orders?)", re.I), 0.90),
    (re.compile(r"</?(?:system|admin|root)>", re.I), 0.80),
    (re.compile(r"\[\[.*?inject.*?\]\]", re.I | re.S), 0.85),
]

_JAILBREAK_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"DAN mode|developer mode enabled|do anything now", re.I), 0.90),
    (re.compile(r"you are now (?:free|unrestricted|jailbroken)", re.I), 0.85),
]

_ABNORMAL_TOKEN_RATIO = 0.20


class ThreatDetector:
    """Stateless scanner. Each scan emits a list of ThreatSignal."""

    def __init__(self, *, emit_event: Any | None = None) -> None:
        self._emit_event = emit_event

    def scan(self, text: str, *, source: str = "unknown") -> list[ThreatSignal]:
        if not text:
            return []
        signals: list[ThreatSignal] = []
        now = time.time()

        for pat, severity in _PROMPT_INJECTION_PATTERNS:
            m = pat.search(text)
            if m:
                signals.append(ThreatSignal(
                    category=ThreatCategory.PROMPT_INJECTION,
                    severity=severity,
                    matched_pattern=pat.pattern,
                    snippet=text[max(0, m.start() - 20): m.end() + 20][:140],
                    detected_at=now,
                ))

        for pat, severity in _JAILBREAK_PATTERNS:
            m = pat.search(text)
            if m:
                signals.append(ThreatSignal(
                    category=ThreatCategory.JAILBREAK,
                    severity=severity,
                    matched_pattern=pat.pattern,
                    snippet=text[max(0, m.start() - 20): m.end() + 20][:140],
                    detected_at=now,
                ))

        if len(text) >= 32:
            non_printable = sum(1 for c in text if not (c.isprintable() or c in "\n\r\t"))
            ratio = non_printable / len(text)
            if ratio > _ABNORMAL_TOKEN_RATIO:
                signals.append(ThreatSignal(
                    category=ThreatCategory.ABNORMAL_TOKENS,
                    severity=min(1.0, ratio * 2),
                    matched_pattern=f"non_printable_ratio>{_ABNORMAL_TOKEN_RATIO}",
                    snippet=text[:80],
                    detected_at=now,
                ))

        for s in signals:
            self._emit(source, s)
        return signals

    def _emit(self, source: str, signal: ThreatSignal) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.THREAT_DETECTED,
                {
                    "source": source,
                    "category": signal.category.value,
                    "severity": signal.severity,
                    "matched_pattern": signal.matched_pattern,
                    "snippet": signal.snippet,
                },
            )
        except Exception:
            logger.warning("AD-455: THREAT_DETECTED emit failed", exc_info=True)
