"""AD-567d: Anchor provenance composition for dream consolidation.

Carries forward anchor metadata from source episodes into derivative
artifacts (clusters, procedures, convergence reports). Follows the SEEM
RPE principle: **compose** provenance, don't merge.

Cluster anchor summaries aggregate shared/unique fields from source
episodes so downstream consumers (procedures, gap reports, convergence
reports) inherit the evidentiary chain.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def summarize_cluster_anchors(episodes: list[Any]) -> dict[str, Any]:
    """Build a cluster-level anchor summary from constituent episodes.

    Aggregates shared and episode-specific anchor fields across the
    cluster's source episodes. Returns a dict with:
    - ``channels``: unique channels across episodes
    - ``departments``: unique departments
    - ``trigger_types``: unique trigger types
    - ``participants``: unique participant callsigns
    - ``temporal_span``: (earliest_timestamp, latest_timestamp)
    - ``episode_count``: number of episodes with anchors
    - ``per_episode``: list of per-episode anchor summaries (compact)
    """
    channels: set[str] = set()
    departments: set[str] = set()
    trigger_types: set[str] = set()
    participants: set[str] = set()
    timestamps: list[float] = []
    per_episode: list[dict[str, Any]] = []
    anchored_count = 0

    for ep in episodes:
        anchors = getattr(ep, "anchors", None)
        if anchors is None:
            continue
        anchored_count += 1
        ch = getattr(anchors, "channel", "") or ""
        dept = getattr(anchors, "department", "") or ""
        trigger = getattr(anchors, "trigger_type", "") or ""
        parts = getattr(anchors, "participants", []) or []
        trigger_agent = getattr(anchors, "trigger_agent", "") or ""

        if ch:
            channels.add(ch)
        if dept:
            departments.add(dept)
        if trigger:
            trigger_types.add(trigger)
        for p in parts:
            if p:
                participants.add(p)
        if trigger_agent:
            participants.add(trigger_agent)

        ep_ts = getattr(ep, "timestamp", 0.0) or 0.0
        if ep_ts > 0:
            timestamps.append(ep_ts)

        # Compact per-episode record
        per_episode.append({
            "episode_id": getattr(ep, "id", ""),
            "channel": ch,
            "department": dept,
            "trigger_type": trigger,
            "trigger_agent": trigger_agent,
        })

    temporal_span = (
        (min(timestamps), max(timestamps)) if timestamps else (0.0, 0.0)
    )

    return {
        "channels": sorted(channels),
        "departments": sorted(departments),
        "trigger_types": sorted(trigger_types),
        "participants": sorted(participants),
        "temporal_span": list(temporal_span),
        "episode_count": anchored_count,
        "per_episode": per_episode,
    }


def build_procedure_provenance(
    cluster_anchor_summary: dict[str, Any],
    cluster_id: str = "",
) -> list[dict[str, Any]]:
    """Build source_anchors list for a procedure from a cluster's anchor summary.

    Each entry in the returned list represents a source episode's anchor
    context so the procedure retains full evidentiary chain back to the
    experiences that generated it.
    """
    source_anchors: list[dict[str, Any]] = []
    per_episode = cluster_anchor_summary.get("per_episode", [])
    for entry in per_episode:
        source_anchors.append({
            "episode_id": entry.get("episode_id", ""),
            "channel": entry.get("channel", ""),
            "department": entry.get("department", ""),
            "trigger_type": entry.get("trigger_type", ""),
            "trigger_agent": entry.get("trigger_agent", ""),
            "cluster_id": cluster_id,
        })
    return source_anchors


def enrich_convergence_report(
    report_data: dict[str, Any],
    cluster_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Enrich a convergence report with provenance from contributing entries.

    Adds ``source_anchors`` to the report data dict with per-entry
    provenance (agent, department, path).
    """
    source_anchors: list[dict[str, str]] = []
    for entry in cluster_entries:
        source_anchors.append({
            "agent": entry.get("agent", ""),
            "department": entry.get("department", ""),
            "path": entry.get("path", ""),
        })
    report_data["source_anchors"] = source_anchors
    return report_data
