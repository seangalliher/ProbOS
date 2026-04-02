"""AD-539: Gap report API endpoints."""
from __future__ import annotations

import logging
import time
from typing import Any

import yaml
from fastapi import APIRouter, Depends

from probos.routers.deps import get_runtime

router = APIRouter(prefix="/api/gaps", tags=["gaps"])
logger = logging.getLogger(__name__)


async def _load_gap_reports(runtime: Any, resolved_filter: bool | None = None) -> list[dict]:
    """Load gap reports from Ship's Records."""
    records = runtime.records_store
    if not records:
        return []
    try:
        entries = await records.list_entries(
            directory="reports/gap-reports",
            tags=["ad-539"],
        )
        results = []
        for entry in entries:
            path = entry.get("path", "")
            doc = await records.read_entry(path, reader_id="system")
            if doc:
                content = doc.get("content", "")
                try:
                    data = yaml.safe_load(content) or {}
                except Exception:
                    data = {}
                data["_path"] = path
                fm = entry.get("frontmatter", {})
                for k, v in fm.items():
                    if k not in data:
                        data[k] = v
                # Apply resolved filter
                is_resolved = data.get("resolved", False)
                if resolved_filter is not None and is_resolved != resolved_filter:
                    continue
                results.append(data)
        return results
    except Exception:
        return []


@router.get("")
async def list_gaps(
    agent: str | None = None,
    type: str | None = None,
    priority: str | None = None,
    resolved: bool = False,
    runtime: Any = Depends(get_runtime),
) -> dict:
    """List gap reports with optional filters."""
    reports = await _load_gap_reports(runtime, resolved_filter=resolved)

    if agent:
        agent_lower = agent.lower()
        reports = [
            r for r in reports
            if agent_lower in r.get("agent_id", "").lower()
            or agent_lower in r.get("agent_type", "").lower()
        ]
    if type:
        reports = [r for r in reports if r.get("gap_type", "") == type]
    if priority:
        reports = [r for r in reports if r.get("priority", "") == priority]

    # Clean internal fields
    for r in reports:
        r.pop("_path", None)

    return {"gaps": reports, "count": len(reports)}


@router.get("/summary")
async def gaps_summary(
    runtime: Any = Depends(get_runtime),
) -> dict:
    """Aggregate gap report statistics."""
    all_reports = await _load_gap_reports(runtime)
    open_reports = [r for r in all_reports if not r.get("resolved", False)]
    resolved_reports = [r for r in all_reports if r.get("resolved", False)]

    by_type: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    by_agent: dict[str, int] = {}
    affected_skills: dict[str, int] = {}

    for r in open_reports:
        t = r.get("gap_type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
        p = r.get("priority", "unknown")
        by_priority[p] = by_priority.get(p, 0) + 1
        a = r.get("agent_type", r.get("agent_id", "unknown"))
        by_agent[a] = by_agent.get(a, 0) + 1
        s = r.get("mapped_skill_id", "")
        if s:
            affected_skills[s] = affected_skills.get(s, 0) + 1

    return {
        "total": len(all_reports),
        "open": len(open_reports),
        "resolved": len(resolved_reports),
        "by_type": by_type,
        "by_priority": by_priority,
        "by_agent": by_agent,
        "affected_skills": affected_skills,
    }


@router.get("/{gap_id}")
async def get_gap(
    gap_id: str,
    runtime: Any = Depends(get_runtime),
) -> dict:
    """Get a single gap report by ID."""
    reports = await _load_gap_reports(runtime)
    for r in reports:
        if r.get("id", "") == gap_id or r.get("id", "").startswith(gap_id):
            r.pop("_path", None)
            return {"gap": r}
    return {"error": "not_found", "gap": None}


@router.post("/{gap_id}/check")
async def check_gap(
    gap_id: str,
    runtime: Any = Depends(get_runtime),
) -> dict:
    """Run gap closure check."""
    from probos.cognitive.gap_predictor import check_gap_closure, GapReport

    reports = await _load_gap_reports(runtime)
    match = None
    for r in reports:
        if r.get("id", "") == gap_id or r.get("id", "").startswith(gap_id):
            match = r
            break

    if not match:
        return {"error": "not_found", "resolved": False}

    if match.get("resolved", False):
        return {"resolved": True, "message": "Already resolved"}

    gap = GapReport(
        id=match.get("id", ""),
        agent_id=match.get("agent_id", ""),
        agent_type=match.get("agent_type", ""),
        gap_type=match.get("gap_type", "knowledge"),
        description=match.get("description", ""),
        affected_intent_types=match.get("affected_intent_types", []),
        failure_rate=match.get("failure_rate", 0.0),
        episode_count=match.get("episode_count", 0),
        mapped_skill_id=match.get("mapped_skill_id", ""),
        current_proficiency=match.get("current_proficiency", 0),
        target_proficiency=match.get("target_proficiency", 0),
    )

    # Get services
    skill_service = None
    procedure_store = None
    for agent in runtime.registry.all():
        ps = getattr(agent, "_procedure_store", None)
        if ps:
            procedure_store = ps
            skill_service = getattr(ps, "_skill_service", None)
            break

    closed = await check_gap_closure(gap, skill_service, procedure_store)

    if closed:
        gap.resolved = True
        gap.resolved_at = time.time()
        records = runtime.records_store
        if records:
            try:
                content = yaml.dump(gap.to_dict(), default_flow_style=False, sort_keys=False)
                await records.write_entry(
                    author="system",
                    path=f"reports/gap-reports/{gap.id}.md",
                    content=content,
                    message=f"Gap resolved: {gap.description}",
                    classification="ship",
                    topic="gap_analysis",
                    tags=["ad-539", "resolved"],
                )
            except Exception:
                pass

    match.pop("_path", None)
    return {"resolved": closed, "gap": gap.to_dict()}
