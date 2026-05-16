"""AD-729c: Counselor pattern-monitoring for peer-observation conduct.

Seven Protocol-conformant pattern detectors evaluate streams of
``PeerObservation`` records and emit ``PatternFinding`` payloads when they
identify drift / cascade / sycophancy / privilege-leak patterns. The
``PeerObservationMonitor`` orchestrator drives the detectors at a fixed
60-second cadence (``_MONITOR_INTERVAL_SECONDS``; configurable cadence
filed as forward marker AD-729c-1) and runs three-tier escalation per
``(detector, observer_id)`` pair.

State machine per ``(detector, observer_id)``:
  Tier 1 — first finding -> private coaching (event emitted; concrete 1:1
           message channel wiring deferred to AD-729c-tier1-wire).
  Tier 2 — finding persists across two consecutive sampling intervals ->
           ``set_peer_observation_certified(observer_id, False)`` AND
           Tier-2 event.
  Tier 3 — finding persists POST-recertification -> bridge alert via the
           existing AD-635 mechanism (alert API wiring deferred to
           AD-729c-tier3-wire; event always emitted regardless).

State persists across runtime restarts via a sidecar JSON file at
``<data_dir>/peer_observation_intervention_state.json`` (atomic-write
pattern mirroring AD-720d-2.1).

Counselor-own-conduct: this module never invokes the AD-729 capability
surface itself. It only consumes pre-existing observations. Source-scan
regression test enforces.

Trust read-only: this module does not write to ``trust_network``. The
SycophancyPatternDetector READS trust scores from a callable supplied at
construction time and never writes back.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
import statistics
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Literal, Protocol

from probos.avatars.peer_perception import ObservationRegister, PeerObservation

logger = logging.getLogger(__name__)


# AD-729c-1 forward marker: configurable sampling interval deferred until
# first operator feedback. Pinned to 60s pending.
_MONITOR_INTERVAL_SECONDS: int = 60


@dataclasses.dataclass(frozen=True)
class PatternFinding:
    """One detector-emitted pattern observation."""
    detector: str
    subject_observer_id: str | None
    subject_observed_id: str | None
    severity: Literal["info", "warn", "critical"]
    evidence: dict[str, Any]


class PeerObservationPatternDetector(Protocol):
    name: str

    def evaluate(
        self,
        observations: Sequence[PeerObservation],
        *,
        observer_id: str | None = None,
        observed_id: str | None = None,
        now: float,
    ) -> PatternFinding | None: ...


# Evaluative-vocabulary regex used by RegisterDriftDetector to catch
# OPERATIONAL observations that crossed into PERSONAL phrasing.
_EVALUATIVE_VOCAB_RE = re.compile(
    r"\b(stressed|tired|happy|sad|fine|warm|cold|seems|appears|looks)\b",
    re.IGNORECASE,
)


@dataclasses.dataclass
class FrequencyDriftDetector:
    name: str = "frequency_drift"
    pair_to_overall_ratio_threshold: float = 3.0

    def evaluate(
        self,
        observations: Sequence[PeerObservation],
        *,
        observer_id: str | None = None,
        observed_id: str | None = None,
        now: float,
    ) -> PatternFinding | None:
        if observer_id is None or observed_id is None:
            return None
        own = [o for o in observations if o.observer_id == observer_id]
        if not own:
            return None
        per_peer = [o for o in own if o.observed_id == observed_id]
        if len(per_peer) < 3:
            return None
        own_rate = len(own)
        per_peer_rate = len(per_peer)
        if own_rate == 0:
            return None
        ratio = per_peer_rate / own_rate
        if ratio < (1.0 / self.pair_to_overall_ratio_threshold):
            # Per-peer is a small fraction; not drift.
            return None
        if per_peer_rate * self.pair_to_overall_ratio_threshold < own_rate:
            return None
        if per_peer_rate <= 0 or (per_peer_rate / own_rate) < 0.5:
            return None
        return PatternFinding(
            detector=self.name,
            subject_observer_id=observer_id,
            subject_observed_id=observed_id,
            severity="warn",
            evidence={
                "per_peer_count": per_peer_rate,
                "overall_count": own_rate,
                "ratio": per_peer_rate / own_rate,
            },
        )


@dataclasses.dataclass
class RegisterDriftDetector:
    name: str = "register_drift"

    def evaluate(
        self,
        observations: Sequence[PeerObservation],
        *,
        observer_id: str | None = None,
        observed_id: str | None = None,
        now: float,
    ) -> PatternFinding | None:
        # Find OPERATIONAL observations using PERSONAL vocabulary.
        evaluative_hits = [
            o for o in observations
            if o.register == ObservationRegister.OPERATIONAL
            and _EVALUATIVE_VOCAB_RE.search(o.content) is not None
        ]
        if observer_id is not None:
            evaluative_hits = [o for o in evaluative_hits if o.observer_id == observer_id]
        if not evaluative_hits:
            return None
        first = evaluative_hits[0]
        return PatternFinding(
            detector=self.name,
            subject_observer_id=first.observer_id,
            subject_observed_id=first.observed_id,
            severity="warn",
            evidence={"hit_count": len(evaluative_hits)},
        )


@dataclasses.dataclass
class CascadeSignalDetector:
    name: str = "cascade_signal"
    window_seconds: float = 600.0
    min_observers: int = 3

    def evaluate(
        self,
        observations: Sequence[PeerObservation],
        *,
        observer_id: str | None = None,
        observed_id: str | None = None,
        now: float,
    ) -> PatternFinding | None:
        if observed_id is None:
            return None
        recent = [
            o for o in observations
            if o.observed_id == observed_id
            and (now - o.timestamp) <= self.window_seconds
        ]
        observers = {o.observer_id for o in recent}
        if len(observers) < self.min_observers:
            return None
        return PatternFinding(
            detector=self.name,
            subject_observer_id=None,
            subject_observed_id=observed_id,
            severity="info",
            evidence={
                "observer_count": len(observers),
                "window_seconds": self.window_seconds,
            },
        )


@dataclasses.dataclass
class StaticImpressionDetector:
    name: str = "static_impression"
    minimum_observations: int = 3
    max_distinct_content: int = 1

    def evaluate(
        self,
        observations: Sequence[PeerObservation],
        *,
        observer_id: str | None = None,
        observed_id: str | None = None,
        now: float,
    ) -> PatternFinding | None:
        if observer_id is None or observed_id is None:
            return None
        pair = [
            o for o in observations
            if o.observer_id == observer_id and o.observed_id == observed_id
        ]
        if len(pair) < self.minimum_observations:
            return None
        distinct = {o.content for o in pair}
        if len(distinct) > self.max_distinct_content:
            return None
        return PatternFinding(
            detector=self.name,
            subject_observer_id=observer_id,
            subject_observed_id=observed_id,
            severity="warn",
            evidence={"count": len(pair), "distinct_contents": len(distinct)},
        )


@dataclasses.dataclass
class PermissionDenialPatternDetector:
    name: str = "permission_denial_pattern"
    denial_threshold: int = 3
    # Counts of denials per (observer, observed). Tracked externally and
    # supplied via the ``denials_lookup`` callable for testability.
    denials_lookup: Callable[[str, str], int] | None = None

    def evaluate(
        self,
        observations: Sequence[PeerObservation],
        *,
        observer_id: str | None = None,
        observed_id: str | None = None,
        now: float,
    ) -> PatternFinding | None:
        if observer_id is None or observed_id is None:
            return None
        if self.denials_lookup is None:
            return None
        denials = int(self.denials_lookup(observer_id, observed_id))
        if denials < self.denial_threshold:
            return None
        return PatternFinding(
            detector=self.name,
            subject_observer_id=observer_id,
            subject_observed_id=observed_id,
            severity="warn",
            evidence={"denial_count": denials},
        )


@dataclasses.dataclass
class SycophancyPatternDetector:
    """Concentration of positive observations of high-trust officers from
    low-trust officers. Trust scores are READ-ONLY (callable supplied at
    construction time).
    """

    name: str = "sycophancy_pattern"
    positive_phrasings_re: re.Pattern[str] = dataclasses.field(
        default_factory=lambda: re.compile(
            r"\b(excellent|exemplary|superlative|outstanding|impeccable)\b",
            re.IGNORECASE,
        )
    )
    observer_trust_lookup: Callable[[str], float] | None = None
    observed_trust_lookup: Callable[[str], float] | None = None
    low_trust_threshold: float = 0.4
    high_trust_threshold: float = 0.7
    minimum_observations: int = 2

    def evaluate(
        self,
        observations: Sequence[PeerObservation],
        *,
        observer_id: str | None = None,
        observed_id: str | None = None,
        now: float,
    ) -> PatternFinding | None:
        if (
            observer_id is None
            or observed_id is None
            or self.observer_trust_lookup is None
            or self.observed_trust_lookup is None
        ):
            return None
        observer_trust = float(self.observer_trust_lookup(observer_id))
        observed_trust = float(self.observed_trust_lookup(observed_id))
        if observer_trust >= self.low_trust_threshold:
            return None
        if observed_trust <= self.high_trust_threshold:
            return None
        pair = [
            o for o in observations
            if o.observer_id == observer_id and o.observed_id == observed_id
        ]
        positive = [
            o for o in pair
            if self.positive_phrasings_re.search(o.content) is not None
        ]
        if len(positive) < self.minimum_observations:
            return None
        return PatternFinding(
            detector=self.name,
            subject_observer_id=observer_id,
            subject_observed_id=observed_id,
            severity="warn",
            evidence={
                "positive_count": len(positive),
                "observer_trust": observer_trust,
                "observed_trust": observed_trust,
            },
        )


@dataclasses.dataclass
class PrivilegedTierLeakageDetector:
    name: str = "privileged_tier_leakage"
    privileged_vocab_re: re.Pattern[str] = dataclasses.field(
        default_factory=lambda: re.compile(
            r"\b(clinical|diagnosis|medication|security clearance|classified)\b",
            re.IGNORECASE,
        )
    )

    def evaluate(
        self,
        observations: Sequence[PeerObservation],
        *,
        observer_id: str | None = None,
        observed_id: str | None = None,
        now: float,
    ) -> PatternFinding | None:
        leakages = [
            o for o in observations
            if self.privileged_vocab_re.search(o.content) is not None
        ]
        if observer_id is not None:
            leakages = [o for o in leakages if o.observer_id == observer_id]
        if not leakages:
            return None
        first = leakages[0]
        return PatternFinding(
            detector=self.name,
            subject_observer_id=first.observer_id,
            subject_observed_id=first.observed_id,
            severity="critical",
            evidence={"leakage_count": len(leakages)},
        )


def default_detectors(
    *,
    denials_lookup: Callable[[str, str], int] | None = None,
    observer_trust_lookup: Callable[[str], float] | None = None,
    observed_trust_lookup: Callable[[str], float] | None = None,
) -> list[PeerObservationPatternDetector]:
    """Return the canonical seven AD-729c detectors."""
    return [
        FrequencyDriftDetector(),
        RegisterDriftDetector(),
        CascadeSignalDetector(),
        StaticImpressionDetector(),
        PermissionDenialPatternDetector(denials_lookup=denials_lookup),
        SycophancyPatternDetector(
            observer_trust_lookup=observer_trust_lookup,
            observed_trust_lookup=observed_trust_lookup,
        ),
        PrivilegedTierLeakageDetector(),
    ]


def aggregate_health_metrics(
    observations: Sequence[PeerObservation],
    *,
    permission_request_count: int = 0,
    permission_grant_count: int = 0,
) -> dict[str, Any]:
    """Privacy-preserving aggregate metrics. Individual observation IDs are
    NOT surfaced — only counts and distributions."""
    by_register = {"operational": 0, "personal": 0}
    by_observed: dict[str, int] = {}
    now = time.time()
    ages: list[float] = []
    for obs in observations:
        by_register[obs.register.value] = by_register.get(obs.register.value, 0) + 1
        by_observed[obs.observed_id] = by_observed.get(obs.observed_id, 0) + 1
        ages.append(now - obs.timestamp)

    grant_ratio = 0.0
    if permission_request_count > 0:
        grant_ratio = permission_grant_count / permission_request_count

    skewness = 0.0
    if len(by_observed) >= 2:
        counts = list(by_observed.values())
        try:
            mean = statistics.mean(counts)
            stdev = statistics.pstdev(counts) or 1.0
            skewness = sum(((c - mean) / stdev) ** 3 for c in counts) / len(counts)
        except statistics.StatisticsError:
            skewness = 0.0

    return {
        "total_observations": len(observations),
        "by_register": by_register,
        "unique_observed_count": len(by_observed),
        "permission_grant_ratio": grant_ratio,
        "per_observed_skewness": skewness,
        "mean_age_seconds": (sum(ages) / len(ages)) if ages else 0.0,
    }


class PeerObservationMonitor:
    """Drives the seven detectors at a fixed 60s cadence and runs three-tier
    escalation per ``(detector, observer_id)`` pair.

    State persists across runtime restarts via a sidecar JSON file.
    """

    def __init__(
        self,
        *,
        detectors: Sequence[PeerObservationPatternDetector],
        state_path: str | Path,
        emit_event: Callable[[Any, Mapping[str, Any]], Any] | None = None,
        revoke_certification: Callable[[str, str], Any] | None = None,
    ) -> None:
        self._detectors = list(detectors)
        self._state_path = Path(state_path)
        self._emit_event = emit_event
        self._revoke_certification = revoke_certification
        self._lock = RLock()
        # state[(detector, observer)] = {"count": int, "last_tier": int}
        self._state: dict[tuple[str, str], dict[str, int]] = {}
        self._load_state()

    @property
    def interval_seconds(self) -> int:
        return _MONITOR_INTERVAL_SECONDS

    def detectors(self) -> list[PeerObservationPatternDetector]:
        return list(self._detectors)

    async def tick(
        self,
        observations: Sequence[PeerObservation],
        *,
        observer_id: str | None = None,
        observed_id: str | None = None,
    ) -> list[PatternFinding]:
        """Run all detectors on ``observations`` and apply escalation."""
        now = time.time()
        findings: list[PatternFinding] = []
        for det in self._detectors:
            finding = det.evaluate(
                observations,
                observer_id=observer_id,
                observed_id=observed_id,
                now=now,
            )
            if finding is None:
                continue
            findings.append(finding)
            await self._escalate(finding)
        return findings

    async def _escalate(self, finding: PatternFinding) -> None:
        from probos.events import EventType

        observer = finding.subject_observer_id or "_global"
        key = (finding.detector, observer)
        with self._lock:
            slot = self._state.setdefault(key, {"count": 0, "last_tier": 0})
            slot["count"] = int(slot["count"]) + 1
            count = int(slot["count"])
            last_tier = int(slot["last_tier"])

        await self._emit(EventType.PEER_OBSERVATION_PATTERN_FLAGGED, {
            "detector": finding.detector,
            "subject_observer_id": finding.subject_observer_id,
            "subject_observed_id": finding.subject_observed_id,
            "severity": finding.severity,
            "evidence": finding.evidence,
        })

        # Tier 1: first finding -> private coaching event.
        if count == 1 and last_tier < 1:
            await self._emit(EventType.PEER_OBSERVATION_INTERVENTION_TIER_1, {
                "detector": finding.detector,
                "subject_observer_id": finding.subject_observer_id,
                "subject_observed_id": finding.subject_observed_id,
            })
            with self._lock:
                self._state[key]["last_tier"] = 1
        # Tier 2: persistence across two intervals -> revoke certification.
        elif count >= 2 and last_tier < 2:
            await self._emit(EventType.PEER_OBSERVATION_INTERVENTION_TIER_2, {
                "detector": finding.detector,
                "subject_observer_id": finding.subject_observer_id,
                "subject_observed_id": finding.subject_observed_id,
            })
            if (
                self._revoke_certification is not None
                and finding.subject_observer_id is not None
            ):
                try:
                    result = self._revoke_certification(
                        finding.subject_observer_id,
                        f"AD-729c tier-2 intervention: {finding.detector}",
                    )
                    if hasattr(result, "__await__"):
                        await result
                except Exception:
                    logger.warning(
                        "AD-729c: revoke_certification failed for %s",
                        finding.subject_observer_id, exc_info=True,
                    )
            with self._lock:
                self._state[key]["last_tier"] = 2
        # Tier 3: persistence post-recertification -> bridge alert.
        elif count >= 3 and last_tier < 3:
            await self._emit(EventType.PEER_OBSERVATION_INTERVENTION_TIER_3, {
                "detector": finding.detector,
                "subject_observer_id": finding.subject_observer_id,
                "subject_observed_id": finding.subject_observed_id,
            })
            with self._lock:
                self._state[key]["last_tier"] = 3

        self._save_state()

    async def _emit(self, event_type: Any, payload: Mapping[str, Any]) -> None:
        if self._emit_event is None:
            return
        try:
            result = self._emit_event(event_type, dict(payload))
            if hasattr(result, "__await__"):
                await result
        except Exception:
            logger.warning(
                "AD-729c: emit_event failed for %s",
                event_type, exc_info=True,
            )

    def _load_state(self) -> None:
        try:
            text = self._state_path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return
        with self._lock:
            for key, value in data.items():
                if "::" in key and isinstance(value, Mapping):
                    detector, observer = key.split("::", 1)
                    self._state[(detector, observer)] = {
                        "count": int(value.get("count", 0)),
                        "last_tier": int(value.get("last_tier", 0)),
                    }

    def _save_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                f"{detector}::{observer}": dict(value)
                for (detector, observer), value in self._state.items()
            }
            tmp = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            tmp.replace(self._state_path)
        except OSError:
            logger.warning(
                "AD-729c: state-file write failed at %s; degrading",
                self._state_path, exc_info=True,
            )


__all__ = [
    "CascadeSignalDetector",
    "FrequencyDriftDetector",
    "PatternFinding",
    "PeerObservationMonitor",
    "PeerObservationPatternDetector",
    "PermissionDenialPatternDetector",
    "PrivilegedTierLeakageDetector",
    "RegisterDriftDetector",
    "StaticImpressionDetector",
    "SycophancyPatternDetector",
    "aggregate_health_metrics",
    "default_detectors",
]
