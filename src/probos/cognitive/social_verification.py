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
    independent_anchor_count: int  # How many have INDEPENDENT anchors
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


def compute_anchor_independence(episodes: list[Any]) -> float:
    """Compute anchor independence score for a set of episodes.

    Returns 0.0-1.0: ratio of independently anchored episode pairs
    to total episode pairs.
    """
    if len(episodes) < 2:
        return 0.0

    total_pairs = 0
    independent_pairs = 0

    for i in range(len(episodes)):
        for j in range(i + 1, len(episodes)):
            total_pairs += 1
            a = getattr(episodes[i], "anchors", None)
            b = getattr(episodes[j], "anchors", None)
            if _are_independently_anchored(a, b) or _time_separated(episodes[i], episodes[j]):
                independent_pairs += 1

    return independent_pairs / total_pairs if total_pairs > 0 else 0.0


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
        independence = compute_anchor_independence(qualified)

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
            0.5 * agent_ratio + 0.3 * independence + 0.2 * mean_confidence,
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
        anchor_summary: dict[str, Any] = {
            "shared_channels": sorted(channels),
            "shared_departments": matching_departments,
            "unique_participants": sorted(all_participants),
            "time_span_seconds": time_span,
        }

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
        independence = compute_anchor_independence(matched_episodes)
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
