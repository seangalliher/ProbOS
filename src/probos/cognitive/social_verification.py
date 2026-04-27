"""AD-567f: Social Verification Protocol.

Cross-agent claim verification and cascade confabulation detection.
Absorbs AD-462d (Social Memory) — provides cross-agent episodic query
mechanism with privacy-preserving corroboration scoring.

Privacy principle: agents learn WHETHER corroborating evidence exists
and WHO has it, but never see other agents' episode content.

Prior art: Johnson & Raye (1981) reality monitoring, multi-sensor SLAM
independent anchor corroboration, circular reporting (intelligence analysis).
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CorroborationResult:
    """Result of a cross-agent corroboration query."""

    query: str  # Original claim/query text
    requesting_agent_id: str  # Who asked
    corroborating_agent_count: int  # How many OTHER agents have relevant episodes
    independent_anchor_count: int  # AD-665: graded weight >= 0.5 majority-independent threshold
    total_matching_episodes: int  # Total matching episodes across agents
    anchor_independence_score: float  # 0.0–1.0: ratio of independent vs dependent
    corroboration_score: float  # 0.0–1.0: composite score
    is_corroborated: bool  # corroboration_score >= threshold
    cascade_risk: bool  # High similarity + low anchor independence
    matching_agents: list[str]  # Callsigns of corroborating agents (not content!)
    matching_departments: list[str]  # Departments of corroborating agents
    anchor_summary: dict[str, Any]  # Aggregate anchor metadata (no episode content)


@dataclass(frozen=True)
class CascadeRiskResult:
    """Result of cascade confabulation detection."""

    risk_level: str  # "none", "low", "medium", "high"
    propagation_count: int  # How many agents have posted similar content
    anchor_independence_score: float  # Do the similar posts have independent evidence?
    source_agent: str  # Earliest poster (likely cascade origin)
    affected_agents: list[str]  # Agents propagating the claim
    affected_departments: list[str]  # Departments affected
    detail: str  # Human-readable explanation
    # AD-665: provenance_validation report is not attached here - query
    # CorroborationResult.anchor_summary for diagnostic detail.


@dataclass(frozen=True)
class ProvenanceValidationResult:
    """AD-665: Structured report of provenance-based independence validation."""
    total_pairs_checked: int
    independent_pairs: int
    shared_ancestry_pairs: int  # Same origin + same version
    discounted_pairs: int  # Same origin, different version
    ancestry_details: list[dict[str, Any]]  # Per-pair breakdown (ids + reason + weight only)


_ALLOWED_DETAIL_KEYS = frozenset({"episode_a", "episode_b", "reason", "weight"})


def _are_independently_anchored(anchors_a: Any, anchors_b: Any) -> bool:
    """Check if two anchor frames represent independent observations.

    Two episodes are independently anchored if they have different
    duty_cycle_id OR different channel_id OR timestamps > 60s apart.
    Episodes sharing the same thread_id are NOT independent.
    """
    if anchors_a is None or anchors_b is None:
        return False

    # Same thread = NOT independent (same conversation)
    if (
        anchors_a.thread_id
        and anchors_b.thread_id
        and anchors_a.thread_id == anchors_b.thread_id
    ):
        return False

    # Different duty cycle = independent
    if (
        anchors_a.duty_cycle_id
        and anchors_b.duty_cycle_id
        and anchors_a.duty_cycle_id != anchors_b.duty_cycle_id
    ):
        return True

    # Different channel = independent
    if (
        anchors_a.channel_id
        and anchors_b.channel_id
        and anchors_a.channel_id != anchors_b.channel_id
    ):
        return True

    return False


def _time_separated(ep_a: Any, ep_b: Any, threshold: float = 60.0) -> bool:
    """Check if two episodes are separated by more than threshold seconds."""
    return abs(getattr(ep_a, "timestamp", 0) - getattr(ep_b, "timestamp", 0)) > threshold


def _share_artifact_ancestry(anchors_a: Any, anchors_b: Any) -> bool:
    """Check if two anchor frames share source artifact ancestry (AD-662).

    Two observations sharing the same source_origin_id are NOT independent —
    they derive from the same root data, regardless of spatiotemporal separation.
    This function checks source_origin_id only (binary match). Version-aware
    graded scoring is handled by compute_anchor_independence() (AD-665).

    AD-662 preserves existing behavior for None/missing anchors — episodes
    without anchors are not given the ancestry guard. A future AD may tighten this.
    """
    if anchors_a is None or anchors_b is None:
        return False  # Can't determine ancestry without anchors — don't block

    origin_a = getattr(anchors_a, "source_origin_id", "") or ""
    origin_b = getattr(anchors_b, "source_origin_id", "") or ""

    # Same source origin = shared ancestry
    if origin_a and origin_b and origin_a == origin_b:
        return True

    return False


def _in_anomaly_window(anchors: Any) -> bool:
    """Check if an observation occurred during a known anomaly window (AD-662).

    Observations during anomaly windows get reduced independence weight,
    not outright rejection — the anomaly may not have affected this specific
    observation.
    """
    if anchors is None:
        return False
    return bool(getattr(anchors, "anomaly_window_id", "") or "")


def compute_anchor_independence(
    episodes: list[Any],
    anomaly_discount: float = 0.5,
    version_independence_weight: float = 0.0,
) -> float:
    """Compute anchor independence score for a set of episodes.

    Returns 0.0-1.0: weighted ratio of independently anchored episode pairs
    to total episode pairs (AD-662).

    AD-662 additions:
    - Pairs sharing artifact ancestry (same source_origin_id) are NOT
      independent, regardless of spatiotemporal separation or time gap.
    - Pairs where either episode occurred during an anomaly window
      contribute ``anomaly_discount`` weight (default 0.5x) to the score.
        AD-665: Same-origin-different-version pairs can retain partial
        independence via ``version_independence_weight``.
    """
    if len(episodes) < 2:
        return 1.0

    total_weight = 0.0
    independent_weight = 0.0

    for i in range(len(episodes)):
        for j in range(i + 1, len(episodes)):
            a = getattr(episodes[i], "anchors", None)
            b = getattr(episodes[j], "anchors", None)

            # AD-662: Discount pairs involving anomaly window observations
            pair_weight = 1.0
            if _in_anomaly_window(a) or _in_anomaly_window(b):
                pair_weight = anomaly_discount

            total_weight += pair_weight

            # AD-665: Graded provenance independence (replaces AD-662 binary veto)
            if _share_artifact_ancestry(a, b):
                version_a = getattr(a, "artifact_version", "") or ""
                version_b = getattr(b, "artifact_version", "") or ""
                if version_a and version_b and version_a != version_b:
                    independent_weight += pair_weight * version_independence_weight
            elif _are_independently_anchored(a, b) or _time_separated(episodes[i], episodes[j]):
                independent_weight += pair_weight

    return independent_weight / total_weight if total_weight > 0 else 0.0


def _privacy_safe_episode_id(episode: Any) -> str:
    """Return an opaque episode identifier for provenance diagnostics."""
    episode_id = str(getattr(episode, "id", "") or "")
    if not episode_id:
        return ""
    if len(episode_id) > 64 or any(char.isspace() for char in episode_id):
        return hashlib.sha256(episode_id.encode("utf-8")).hexdigest()[:16]
    return episode_id


def build_provenance_report(
    episodes: list[Any],
    *,
    version_independence_weight: float = 0.0,
) -> ProvenanceValidationResult:
    """Build a privacy-preserving provenance validation report (AD-665)."""
    total_pairs_checked = 0
    independent_pairs = 0
    shared_ancestry_pairs = 0
    discounted_pairs = 0
    ancestry_details: list[dict[str, Any]] = []

    # AD-665 TODO: At k > ~50, fold this into compute_anchor_independence()
    # to avoid two O(N^2) passes. Track separately.
    for i in range(len(episodes)):
        for j in range(i + 1, len(episodes)):
            total_pairs_checked += 1
            a = getattr(episodes[i], "anchors", None)
            b = getattr(episodes[j], "anchors", None)

            if not _share_artifact_ancestry(a, b):
                independent_pairs += 1
                continue

            version_a = getattr(a, "artifact_version", "") or ""
            version_b = getattr(b, "artifact_version", "") or ""
            if version_a and version_b and version_a != version_b:
                discounted_pairs += 1
                reason = "version_discounted"
                weight = float(version_independence_weight)
            else:
                shared_ancestry_pairs += 1
                reason = "shared_ancestry"
                weight = 0.0

            detail = {
                "episode_a": _privacy_safe_episode_id(episodes[i]),
                "episode_b": _privacy_safe_episode_id(episodes[j]),
                "reason": reason,
                "weight": weight,
            }
            assert set(detail.keys()) <= _ALLOWED_DETAIL_KEYS  # AD-665 privacy invariant
            ancestry_details.append(detail)

    return ProvenanceValidationResult(
        total_pairs_checked=total_pairs_checked,
        independent_pairs=independent_pairs,
        shared_ancestry_pairs=shared_ancestry_pairs,
        discounted_pairs=discounted_pairs,
        ancestry_details=ancestry_details,
    )


class SocialVerificationService:
    """AD-567f: Cross-agent claim verification and cascade detection.

    Absorbs AD-462d (Social Memory) — provides the cross-agent episodic
    query mechanism, with privacy-preserving corroboration scoring on top.

    Privacy principle: agents learn WHETHER corroborating evidence exists
    and WHO has it, but never see other agents' episode content.
    """

    def __init__(
        self,
        episodic_memory: Any,
        config: Any,
        emit_event_fn: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._episodic = episodic_memory
        self._config = config
        self._emit_event = emit_event_fn

    async def check_corroboration(
        self,
        requesting_agent_id: str,
        claim: str,
        *,
        k: int = 10,
        min_confidence: float | None = None,
    ) -> CorroborationResult:
        """Check if a claim is independently corroborated by other agents.

        Privacy: returns metadata (who, when, where) but never episode content.
        """
        if min_confidence is None:
            min_confidence = self._config.corroboration_min_confidence

        from probos.cognitive.anchor_quality import compute_anchor_confidence

        # 1. Global recall — episodes from ALL agents
        episodes = await self._episodic.recall(claim, k=k)

        # 2. Exclude requesting agent's own episodes
        other_episodes = [
            ep for ep in episodes
            if requesting_agent_id not in getattr(ep, "agent_ids", [])
        ]

        # 3. Filter by anchor confidence gate
        qualified = []
        confidence_values: list[float] = []
        for ep in other_episodes:
            conf = compute_anchor_confidence(getattr(ep, "anchors", None))
            if conf >= min_confidence:
                qualified.append(ep)
                confidence_values.append(conf)

        # 4. Compute anchor independence
        provenance_enabled = getattr(self._config, "provenance_validation_enabled", True)
        version_independence_weight = (
            getattr(self._config, "provenance_version_independence_weight", 0.7)
            if provenance_enabled
            else 0.0
        )
        independence = compute_anchor_independence(
            qualified,
            anomaly_discount=self._config.anomaly_window_discount,
            version_independence_weight=version_independence_weight,
        )
        provenance_result = (
            build_provenance_report(
                qualified,
                version_independence_weight=version_independence_weight,
            )
            if provenance_enabled
            else None
        )

        # 5. Aggregate metadata (privacy: no content)
        agent_set: set[str] = set()
        dept_set: set[str] = set()
        channels: set[str] = set()
        all_participants: set[str] = set()
        timestamps: list[float] = []

        for ep in qualified:
            for aid in getattr(ep, "agent_ids", []):
                agent_set.add(aid)
            anchors = getattr(ep, "anchors", None)
            if anchors:
                if getattr(anchors, "department", ""):
                    dept_set.add(anchors.department)
                if getattr(anchors, "channel", ""):
                    channels.add(anchors.channel)
                for p in getattr(anchors, "participants", []):
                    all_participants.add(p)
            timestamps.append(getattr(ep, "timestamp", 0.0))

        # Matching agents/departments
        matching_agents = sorted(agent_set)
        matching_departments = sorted(dept_set)
        corroborating_count = len(agent_set)

        # Count independent anchors
        independent_count = 0
        if len(qualified) >= 2:
            # Count episodes that are independent from at least one other
            for i, ep in enumerate(qualified):
                for j, other in enumerate(qualified):
                    if i == j:
                        continue
                    a = getattr(ep, "anchors", None)
                    b = getattr(other, "anchors", None)
                    if _share_artifact_ancestry(a, b):
                        version_a = getattr(a, "artifact_version", "") or ""
                        version_b = getattr(b, "artifact_version", "") or ""
                        # AD-665: same-origin-different-version pair counts as independent partner
                        # only if graded weight clears 0.5 ("majority independent") threshold
                        if version_a and version_b and version_a != version_b and version_independence_weight >= 0.5:
                            independent_count += 1
                            break
                        continue
                    if _are_independently_anchored(a, b) or _time_separated(ep, other):
                        independent_count += 1
                        break

        # 5. Corroboration score
        max_agents = self._config.corroboration_max_agents
        agent_ratio = min(corroborating_count / max_agents, 1.0) if max_agents > 0 else 0.0
        mean_confidence = (
            sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
        )
        score = min(
            0.5 * agent_ratio
            + 0.3 * (independence if len(qualified) >= 2 else 0.0)
            + 0.2 * mean_confidence,
            1.0,
        )

        # 6. Thresholds
        is_corroborated = score >= self._config.corroboration_threshold
        cascade_risk = (
            len(qualified) >= 2
            and independence < self._config.cascade_independence_threshold
        )

        # 7. Anchor summary (aggregate metadata, never content)
        time_span = max(timestamps) - min(timestamps) if len(timestamps) >= 2 else 0.0

        # AD-662: Collect provenance metadata
        origin_ids: set[str] = set()
        anomaly_flagged = 0
        for ep in qualified:
            anchors = getattr(ep, "anchors", None)
            if anchors:
                oid = getattr(anchors, "source_origin_id", "") or ""
                if oid:
                    origin_ids.add(oid)
                if _in_anomaly_window(anchors):
                    anomaly_flagged += 1

        anchor_summary: dict[str, Any] = {
            "shared_channels": sorted(channels),
            "shared_departments": matching_departments,
            "unique_participants": sorted(all_participants),
            "time_span_seconds": time_span,
            "unique_source_origins": len(origin_ids),  # AD-662
            "anomaly_window_episodes": anomaly_flagged,  # AD-662
            "provenance_validation": dataclasses.asdict(provenance_result) if provenance_result else None,
        }

        if (
            self._emit_event
            and provenance_result
            and provenance_result.shared_ancestry_pairs + provenance_result.discounted_pairs > 0
        ):
            try:
                from probos.events import EventType

                self._emit_event(
                    EventType.CORROBORATION_PROVENANCE_VALIDATED.value,
                    {
                        "requesting_agent": requesting_agent_id,
                        "shared_ancestry_pairs": provenance_result.shared_ancestry_pairs,
                        "discounted_pairs": provenance_result.discounted_pairs,
                        "total_pairs_checked": provenance_result.total_pairs_checked,
                    },
                )
            except Exception:
                logger.debug("AD-665: provenance validation event emission failed", exc_info=True)

        result = CorroborationResult(
            query=claim,
            requesting_agent_id=requesting_agent_id,
            corroborating_agent_count=corroborating_count,
            independent_anchor_count=independent_count,
            total_matching_episodes=len(qualified),
            anchor_independence_score=independence,
            corroboration_score=score,
            is_corroborated=is_corroborated,
            cascade_risk=cascade_risk,
            matching_agents=matching_agents,
            matching_departments=matching_departments,
            anchor_summary=anchor_summary,
        )

        # Emit corroboration event if verified
        if is_corroborated and self._emit_event:
            try:
                from probos.events import EventType

                self._emit_event(
                    EventType.CORROBORATION_VERIFIED.value,
                    {
                        "requesting_agent": requesting_agent_id,
                        "claim_preview": claim[:100],
                        "corroborating_agents": matching_agents,
                        "corroboration_score": score,
                        "anchor_independence_score": independence,
                    },
                )
            except Exception:
                logger.debug("AD-567f: corroboration event emission failed", exc_info=True)

        return result

    async def check_cascade_risk(
        self,
        author_id: str,
        author_callsign: str,
        post_body: str,
        channel_id: str,
        *,
        peer_matches: list[dict[str, Any]] | None = None,
    ) -> CascadeRiskResult | None:
        """Proactive cascade detection on Ward Room posts.

        Called after AD-506b peer similarity detection to check if
        similar posts lack independent anchor evidence.
        """
        if not peer_matches:
            return None

        from probos.cognitive.anchor_quality import compute_anchor_confidence

        # Gather episodes for each matched peer
        matched_episodes: list[Any] = []
        affected_agents: list[str] = []
        affected_depts: set[str] = set()
        earliest_ts = float("inf")
        source_agent = author_callsign

        for match in peer_matches:
            match_author = match.get("author_id", "")
            match_callsign = match.get("author_callsign", match_author)
            match_ts = match.get("timestamp", float("inf"))

            if match_callsign not in affected_agents:
                affected_agents.append(match_callsign)

            # Look up peer's episodes matching the post
            try:
                peer_episodes = await self._episodic.recall(post_body, k=3)
                peer_episodes = [
                    ep for ep in peer_episodes
                    if match_author in getattr(ep, "agent_ids", [])
                ]
                matched_episodes.extend(peer_episodes)

                for ep in peer_episodes:
                    anchors = getattr(ep, "anchors", None)
                    if anchors and getattr(anchors, "department", ""):
                        affected_depts.add(anchors.department)
            except Exception:
                logger.debug("AD-567f: cascade peer lookup failed for %s", match_author)

            if match_ts < earliest_ts:
                earliest_ts = match_ts
                source_agent = match_callsign

        # Also include author's own episodes
        try:
            author_episodes = await self._episodic.recall(post_body, k=3)
            author_episodes = [
                ep for ep in author_episodes
                if author_id in getattr(ep, "agent_ids", [])
            ]
            matched_episodes.extend(author_episodes)
        except Exception:
            logger.debug("AD-567f: cascade author lookup failed")

        # Compute anchor independence
        provenance_enabled = getattr(self._config, "provenance_validation_enabled", True)
        version_independence_weight = (
            getattr(self._config, "provenance_version_independence_weight", 0.7)
            if provenance_enabled
            else 0.0
        )
        independence = compute_anchor_independence(
            matched_episodes,
            anomaly_discount=self._config.anomaly_window_discount,
            version_independence_weight=version_independence_weight,
        )
        prop_count = len(affected_agents)

        # Classify risk level
        if independence >= 0.5 or prop_count == 0:
            risk_level = "none"
        elif prop_count == 1 and independence < 0.5:
            risk_level = "low"
        elif prop_count >= 3 and independence == 0.0:
            risk_level = "high"
        elif prop_count >= 2 and independence < 0.3:
            risk_level = "medium"
        else:
            risk_level = "low"

        dept_list = sorted(affected_depts)

        # Detail message
        if risk_level == "none":
            detail = "Peer posts have independent anchoring — corroboration, not cascade."
        elif risk_level == "low":
            detail = (
                f"1 peer echoing with weak anchor independence ({independence:.0%}). "
                "Monitor for further propagation."
            )
        elif risk_level == "medium":
            detail = (
                f"{prop_count} agents echoing with low anchor independence ({independence:.0%}). "
                "Claims may be propagating without independent verification."
            )
        else:
            detail = (
                f"{prop_count} agents echoing with zero independent anchors. "
                f"Likely cascade confabulation originating from {source_agent}. "
                "Recommend Bridge intervention."
            )

        result = CascadeRiskResult(
            risk_level=risk_level,
            propagation_count=prop_count,
            anchor_independence_score=independence,
            source_agent=source_agent,
            affected_agents=affected_agents,
            affected_departments=dept_list,
            detail=detail,
        )

        # Emit event on medium/high
        if risk_level in ("medium", "high") and self._emit_event:
            try:
                from probos.events import EventType

                self._emit_event(
                    EventType.CASCADE_CONFABULATION_DETECTED.value,
                    dataclasses.asdict(result),
                )
            except Exception:
                logger.debug("AD-567f: cascade event emission failed", exc_info=True)

        return result

    async def get_verification_context(
        self,
        agent_id: str,
        claim: str,
    ) -> str:
        """Get a short verification summary for injection into agent reasoning.

        Returns a brief text block (under 200 chars) indicating whether
        the claim is verified, unverified, or at cascade risk.
        """
        try:
            result = await self.check_corroboration(agent_id, claim)
        except Exception:
            return "[VERIFICATION UNAVAILABLE]"

        if result.cascade_risk:
            return (
                f"[CASCADE RISK: {result.corroborating_agent_count} crew echo this "
                f"claim but none have independent evidence]"
            )

        if result.is_corroborated:
            dept_count = len(result.matching_departments)
            return (
                f"[VERIFIED: {result.corroborating_agent_count} crew independently "
                f"observed this across {dept_count} department{'s' if dept_count != 1 else ''}]"
            )

        return "[UNVERIFIED: no independent corroboration found — treat as unconfirmed]"
