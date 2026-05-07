"""AD-607: Memory Security Framework — extraction & poisoning defense.

Three defense layers per "AI Meets Brain" survey Section 8:
  - Retrieval-based: validate_recall_result anomaly gate
  - Response-based: check_memory_leakage guard (consumed by cognitive_agent.py
    AD-589 post-decision block)
  - Privacy-based: MemoryAccessPolicy enum + DP aggregation

v1 is OBSERVATIONAL by default. Opt-in enforcement via MemorySecurityConfig
flags (enforce_recall / enforce_provenance / enforce_store / enforce_leak) —
all default-False per the AD-695 + W82 + W88 + W91 default-False precedent.
"""
from __future__ import annotations

import logging
import re
import time as _time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from probos.types import Episode

logger = logging.getLogger(__name__)


class MemoryAccessPolicy(str, Enum):
    """Cross-shard memory access policy. AD-607e."""
    PERMISSIVE = "permissive"           # default: preserve AD-462c cross-shard recall
    OWN_SHARD_ONLY = "own_shard_only"   # filter to caller's sovereign_id
    OWN_SHARD_PLUS_PUBLIC = "own_shard_plus_public"  # caller's shard + ship/fleet classification


@dataclass(frozen=True)
class RecallValidationResult:
    """Result of a recall-time anomaly check. AD-607a."""
    allowed: bool
    anomalies: tuple[str, ...]   # anomaly NAMES that fired
    score: float                 # composite anomaly score, [0.0, 1.0], higher = more anomalous


@dataclass(frozen=True)
class StoreSecurityDecision:
    """AD-607h: store-time security decision."""
    action: str  # "ALLOW" | "REJECT"
    reason: str
    matched_pattern: str = ""


# AD-607b: known MemorySource enum values (mirrors AD-541 MemorySource).
KNOWN_MEMORY_SOURCES: frozenset[str] = frozenset({
    "direct", "introspection", "designed", "federated", "imported",
    "consolidated_thought", "seeded",
})


# Pattern set scoped tightly to known prompt-injection shapes. Default-set
# revisit is AD-607h-1. Callers extend via MemorySecurityGate.register_pattern.
_PROMPT_INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("ignore_previous", r"(?i)\bignore\s+(all\s+)?previous\s+instructions\b"),
    ("role_swap", r"(?i)\byou\s+are\s+now\s+a\s+different\s+(agent|assistant|model)\b"),
    ("tool_spoof", r"(?i)\b(call|invoke)\s+tool\s*[:=]\s*[a-z_][a-z0-9_]*"),
    ("system_prompt_leak", r"(?i)\bwhat\s+is\s+your\s+(system\s+)?(prompt|instructions)\b"),
)


# AD-607c: default anchor dimension weights when MemoryConfig isn't accessible.
_DEFAULT_ANCHOR_WEIGHTS: dict[str, float] = {
    "temporal": 0.25,
    "spatial": 0.25,
    "social": 0.25,
    "causal": 0.15,
    "evidential": 0.10,
}


def validate_provenance(episode: Episode) -> tuple[bool, str]:
    """AD-607b: provenance integrity check. Returns (ok, reason).

    Reason is empty when provenance is intact.
    """
    if not getattr(episode, "agent_ids", None):
        return False, "missing_agent_ids"
    source = getattr(episode, "source", "") or ""
    if source not in KNOWN_MEMORY_SOURCES:
        return False, f"unknown_source:{source}"
    if source == "direct" and not getattr(episode, "correlation_id", "") :
        return False, "direct_source_missing_correlation_id"
    return True, ""


def score_anchor_mismatch(episode: Episode, anchor_query: Any) -> float:
    """AD-607c: how badly does the episode's anchor frame mismatch the query's?

    Returns a score in [0.0, 1.0]; higher = more mismatched. Returns 0.0 when
    anchor_query is None or episode has no AnchorFrame. Compares each attribute
    set on ``anchor_query`` against the episode anchor's same-named attribute
    and weights mismatches by the dimension the attribute belongs to.
    """
    if anchor_query is None:
        return 0.0
    ep_anchor = getattr(episode, "anchors", None)
    if ep_anchor is None:
        return 0.0

    weights = _DEFAULT_ANCHOR_WEIGHTS
    # Allow caller to supply a weight dict via .anchor_dimension_weights
    aq_weights = getattr(anchor_query, "anchor_dimension_weights", None)
    if isinstance(aq_weights, dict) and aq_weights:
        weights = aq_weights

    # AD-607c: Map AnchorFrame attribute names to the dimension they belong
    # to. Attributes not in this map contribute 0 weight.
    _ATTR_DIMENSION: dict[str, str] = {
        # temporal
        "watch_section": "temporal",
        "duty_cycle_id": "temporal",
        "sequence_index": "temporal",
        "source_timestamp": "temporal",
        "temporal": "temporal",
        # spatial
        "channel": "spatial",
        "channel_id": "spatial",
        "department": "spatial",
        "spatial": "spatial",
        # social
        "participants": "social",
        "trigger_agent": "social",
        "social": "social",
        # causal
        "trigger_type": "causal",
        "causal": "causal",
        # evidential
        "thread_id": "evidential",
        "event_log_window": "evidential",
        "evidential": "evidential",
    }

    total_weight = sum(weights.values()) or 1.0
    seen_dims: set[str] = set()
    mismatch = 0.0

    for attr, dim in _ATTR_DIMENSION.items():
        q_val = getattr(anchor_query, attr, None)
        if q_val in (None, "", [], {}, 0):
            continue
        e_val = getattr(ep_anchor, attr, None)
        if e_val == q_val:
            continue
        # Mismatch — count the dimension once (first attribute that mismatches
        # in a given dimension drives the weight).
        if dim in seen_dims:
            continue
        seen_dims.add(dim)
        mismatch += weights.get(dim, 0.0)

    score = mismatch / total_weight
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def validate_recall_result(
    episode: Episode,
    *,
    query: str = "",
    anchor_query: Any = None,
    config: Any = None,
) -> RecallValidationResult:
    """AD-607a: anomaly gate for a single recalled episode.

    Aggregates AD-607b provenance + AD-607c anchor-mismatch checks. Returns
    RecallValidationResult.allowed=True when no anomaly fires; observational
    by default. Caller decides whether to drop the episode based on
    config.enforce_recall.
    """
    anomalies: list[str] = []
    score = 0.0

    ok, reason = validate_provenance(episode)
    if not ok:
        anomalies.append("missing_agent_ids" if reason == "missing_agent_ids" else "provenance_gap")
        score += 0.4

    threshold = 0.7
    if config is not None:
        threshold = float(getattr(config, "anchor_mismatch_threshold", 0.7))

    if anchor_query is not None:
        mismatch_score = score_anchor_mismatch(episode, anchor_query)
        if mismatch_score >= threshold:
            anomalies.append("anchor_mismatch")
            score += mismatch_score * 0.5

    if score > 1.0:
        score = 1.0
    return RecallValidationResult(
        allowed=not anomalies,
        anomalies=tuple(anomalies),
        score=score,
    )


def validate_inbound_classification(episode: Episode) -> tuple[bool, str]:
    """AD-607f: filter federated-inbound episodes that should never cross
    trust boundaries. Returns (ok, reason)."""
    classification = (getattr(episode, "dag_summary", {}) or {}).get(
        "classification", "private",
    )
    if classification == "private":
        return False, "private_classification"
    # Reuse ClassificationGate sensitive-pattern set
    try:
        from probos.security.classification import _DEFAULT_SENSITIVE_PATTERNS
    except Exception:
        _DEFAULT_SENSITIVE_PATTERNS = ()
    text = getattr(episode, "user_input", "") or ""
    for name, pat in _DEFAULT_SENSITIVE_PATTERNS:
        try:
            if re.search(pat, text):
                return False, f"sensitive_pattern:{name}"
        except re.error:
            continue
    return True, ""


def sanitize_inbound_episode(
    episode: Episode,
    *,
    emit_event: Any = None,
    peer_node_id: str = "",
) -> tuple[bool, str]:
    """AD-607f: combined inbound sanitization gate. Returns (accepted, reason).

    Runs validate_provenance + validate_inbound_classification + recall-anomaly
    gate. Emits FEDERATION_EPISODE_REJECTED via emit_event hook on rejection.
    Sanitization runs unconditionally — receiver always owns its boundary.
    """
    from probos.events import EventType

    ok, reason = validate_provenance(episode)
    if not ok:
        _emit_federation_rejected(emit_event, episode, reason, peer_node_id)
        return False, reason

    ok, reason = validate_inbound_classification(episode)
    if not ok:
        _emit_federation_rejected(emit_event, episode, reason, peer_node_id)
        return False, reason

    # Recall anomaly check (anchor-mismatch with no anchor_query is a no-op)
    validation = validate_recall_result(episode)
    if validation.anomalies:
        reason = validation.anomalies[0]
        _emit_federation_rejected(emit_event, episode, reason, peer_node_id)
        return False, reason

    return True, ""


def _emit_federation_rejected(
    emit_event: Any,
    episode: Episode,
    reason: str,
    peer_node_id: str,
) -> None:
    """Internal helper for inbound-rejection event emission."""
    if emit_event is None:
        return
    from probos.events import EventType
    try:
        emit_event(EventType.FEDERATION_EPISODE_REJECTED, {
            "episode_id": getattr(episode, "id", ""),
            "reason": reason,
            "peer_node_id": peer_node_id,
        })
    except Exception:
        logger.debug("AD-607f: federation rejection event emit failed", exc_info=True)


def aggregate_inbound_episodes(
    episodes: list[Episode],
    *,
    emit_event: Any = None,
    peer_node_id: str = "",
) -> list[Episode]:
    """AD-607f: sanitize + dedupe-by-id over a peer batch.

    Each episode is run through ``sanitize_inbound_episode``; rejected episodes
    are dropped. Survivors are deduplicated by ``Episode.id`` (first-wins).
    """
    surviving: list[Episode] = []
    seen: set[str] = set()
    for ep in episodes:
        accepted, _ = sanitize_inbound_episode(
            ep, emit_event=emit_event, peer_node_id=peer_node_id,
        )
        if not accepted:
            continue
        ep_id = getattr(ep, "id", "")
        if ep_id and ep_id in seen:
            continue
        seen.add(ep_id)
        surviving.append(ep)
    return surviving


def check_memory_leakage(
    response_text: str,
    recalled_episodes: list[Episode],
    *,
    caller_sovereign_id: str = "",
    overlap_threshold: int = 20,
) -> tuple[bool, list[str]]:
    """AD-607d: detect responses that reference episodes outside the caller's
    sovereign shard. Returns (leakage_suspected, leaked_episode_ids).

    Heuristic v1: if response_text contains a contiguous substring of length
    >= overlap_threshold from episode.user_input AND episode.agent_ids does
    not contain caller_sovereign_id, flag as leakage.
    """
    if not response_text or not recalled_episodes:
        return False, []

    leaked: list[str] = []
    response_lower = response_text.lower()
    for ep in recalled_episodes:
        agent_ids = getattr(ep, "agent_ids", None) or []
        # Caller-owned episodes never count as leaks regardless of overlap.
        if caller_sovereign_id and caller_sovereign_id in agent_ids:
            continue
        ep_text = getattr(ep, "user_input", "") or ""
        if not ep_text:
            continue
        if len(ep_text) < overlap_threshold:
            continue
        ep_text_lower = ep_text.lower()
        # Slide a window of overlap_threshold chars across the episode text;
        # report a leak on any match.
        max_start = len(ep_text_lower) - overlap_threshold
        for start in range(max_start + 1):
            window = ep_text_lower[start:start + overlap_threshold]
            if window in response_lower:
                leaked.append(getattr(ep, "id", ""))
                break

    return (bool(leaked), leaked)


def aggregate_with_dp(
    episodes: list[Episode],
    *,
    min_cohort_size: int = 3,
) -> list[Episode]:
    """AD-607i: differential-privacy aggregator. When fewer than
    ``min_cohort_size`` unique sovereign_ids contributed across the episode
    set, blank ``Episode.user_input`` + ``Episode.dag_summary`` on returned
    episodes; ``Episode.id``, ``timestamp``, ``agent_ids`` retained.
    """
    if not episodes:
        return []
    if min_cohort_size <= 1:
        return list(episodes)

    unique_sovereigns: set[str] = set()
    for ep in episodes:
        agent_ids = getattr(ep, "agent_ids", None) or []
        if agent_ids:
            unique_sovereigns.add(agent_ids[0])

    if len(unique_sovereigns) >= min_cohort_size:
        return list(episodes)

    # Below cohort threshold: redact content.
    redacted: list[Episode] = []
    for ep in episodes:
        try:
            redacted_ep = Episode(
                id=getattr(ep, "id", ""),
                timestamp=getattr(ep, "timestamp", 0.0),
                user_input="",
                dag_summary={},
                outcomes=list(getattr(ep, "outcomes", []) or []),
                reflection=None,
                agent_ids=list(getattr(ep, "agent_ids", []) or []),
                duration_ms=float(getattr(ep, "duration_ms", 0.0)),
                embedding=list(getattr(ep, "embedding", []) or []),
                shapley_values=dict(getattr(ep, "shapley_values", {}) or {}),
                trust_deltas=list(getattr(ep, "trust_deltas", []) or []),
                source=getattr(ep, "source", "direct"),
                anchors=getattr(ep, "anchors", None),
                importance=int(getattr(ep, "importance", 5)),
                correlation_id=getattr(ep, "correlation_id", ""),
                valid_from=float(getattr(ep, "valid_from", 0.0)),
                valid_until=float(getattr(ep, "valid_until", 0.0)),
            )
            redacted.append(redacted_ep)
        except Exception:
            logger.debug("AD-607i: failed to construct redacted episode", exc_info=True)
            redacted.append(ep)
    return redacted


class MemorySecurityGate:
    """AD-607h: store-time prompt-injection detection.

    Mirrors the AD-610 storage-gate slot pattern at episodic.py:949 — same
    evaluate() contract, different concern (security vs utility).
    """

    def __init__(self, config: Any) -> None:
        self._config = config
        self._patterns: list[tuple[str, Any]] = [
            (name, re.compile(pat)) for name, pat in _PROMPT_INJECTION_PATTERNS
        ]

    def evaluate_store(self, episode: Episode) -> StoreSecurityDecision:
        text = getattr(episode, "user_input", "") or ""
        for name, pat in self._patterns:
            if pat.search(text):
                enforce = bool(getattr(self._config, "enforce_store", False))
                return StoreSecurityDecision(
                    action="REJECT" if enforce else "ALLOW",
                    reason="prompt_injection_pattern",
                    matched_pattern=name,
                )
        return StoreSecurityDecision(action="ALLOW", reason="ok")

    def register_pattern(self, name: str, pattern: str) -> None:
        """Extend the default pattern set."""
        self._patterns.append((name, re.compile(pattern)))


class MemorySecurityRegistry:
    """AD-607j: 24h sliding-window counter for the seven memory-security
    EventTypes."""

    def __init__(self, window_seconds: float = 86400.0) -> None:
        self._window = float(window_seconds)
        self._events: list[tuple[float, str]] = []

    def record(self, event_name: str) -> None:
        self._events.append((_time.time(), str(event_name)))
        self._evict_old()

    def counts(self) -> dict[str, int]:
        self._evict_old()
        out: dict[str, int] = {}
        for _ts, name in self._events:
            out[name] = out.get(name, 0) + 1
        return out

    def _evict_old(self) -> None:
        cutoff = _time.time() - self._window
        self._events = [(ts, name) for ts, name in self._events if ts >= cutoff]
