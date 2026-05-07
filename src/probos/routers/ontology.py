"""ProbOS API — Ontology routes (AD-429a)."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ontology", tags=["ontology"])


@router.get("/vessel")
async def get_vessel(runtime: Any = Depends(get_runtime)) -> Any:
    """Vessel identity and state."""
    if not runtime.ontology:
        return JSONResponse({"error": "Ontology not initialized"}, status_code=503)
    return {
        "identity": asdict(runtime.ontology.get_vessel_identity()),
        "state": asdict(runtime.ontology.get_vessel_state()),
    }


@router.get("/organization")
async def get_organization(runtime: Any = Depends(get_runtime)) -> Any:
    """Full org chart: departments, posts, assignments, chain of command."""
    if not runtime.ontology:
        return JSONResponse({"error": "Ontology not initialized"}, status_code=503)
    ont = runtime.ontology
    return {
        "departments": [asdict(d) for d in ont.get_departments()],
        "posts": [asdict(p) for p in ont.get_posts()],
        "assignments": [asdict(a) for a in ont.get_all_assignments()],
    }


@router.get("/crew/{agent_type}")
async def get_crew_member(agent_type: str, runtime: Any = Depends(get_runtime)) -> Any:
    """Agent's full ontology context — identity, post, department, chain of command."""
    if not runtime.ontology:
        return JSONResponse({"error": "Ontology not initialized"}, status_code=503)
    ctx = runtime.ontology.get_crew_context(agent_type)
    if not ctx:
        return JSONResponse({"error": "Agent not found in ontology"}, status_code=404)
    return ctx


@router.get("/crew-manifest")
async def get_crew_manifest(
    runtime: Any = Depends(get_runtime),
    department: str | None = None,
) -> dict:
    """AD-513: Ship's Crew Manifest — unified crew roster."""
    ont = runtime.ontology
    if not ont:
        return JSONResponse({"error": "Ontology not initialized"}, status_code=503)

    manifest = ont.get_crew_manifest(
        department=department,
        trust_network=getattr(runtime, 'trust_network', None),
        callsign_registry=getattr(runtime, 'callsign_registry', None),
    )

    departments: dict[str, list] = {}
    for entry in manifest:
        dept = entry.get("department", "unassigned") or "unassigned"
        departments.setdefault(dept, []).append(entry)

    vessel = ont.get_vessel_identity()
    return {
        "vessel": {"name": vessel.name, "instance_id": vessel.instance_id},
        "crew_count": len(manifest),
        "departments": departments,
        "manifest": manifest,
    }


@router.get("/graph")
async def get_ontology_graph(
    runtime: Any = Depends(get_runtime),
    include_edges: bool = True,
    max_edges: int = 500,
    max_nodes: int = 200,
    edge_relations: str = "",
) -> Any:
    """AD-520: Spatial Knowledge Explorer — graph snapshot.

    Combines crew-manifest + organization + (optional) knowledge_edges into
    a force-graph-shaped JSON payload {nodes, edges, generated_at}.
    """
    import time as _time
    ont = runtime.ontology
    if not ont:
        return JSONResponse({"error": "Ontology not initialized"}, status_code=503)

    # Department nodes
    nodes: list[dict[str, Any]] = []
    for dept in ont.get_departments():
        d = asdict(dept)
        nodes.append(
            {
                "id": d.get("id"),
                "label": d.get("name") or d.get("id"),
                "type": "department",
                "accent_color": d.get("accent_color", "#666680"),
            }
        )

    # Agent nodes from crew manifest
    manifest = ont.get_crew_manifest(
        trust_network=getattr(runtime, "trust_network", None),
        callsign_registry=getattr(runtime, "callsign_registry", None),
    )
    for entry in manifest:
        nodes.append(
            {
                "id": entry.get("agent_id") or entry.get("agent_type"),
                "label": entry.get("callsign") or entry.get("agent_type"),
                "type": "agent",
                "department": entry.get("department"),
                "rank": entry.get("rank"),
                "trust": entry.get("trust"),
                "post": entry.get("post"),
                "on_watch": entry.get("on_watch", False),
            }
        )

    # Edges: assignment-derived member_of (always)
    edges: list[dict[str, Any]] = []
    for a in ont.get_all_assignments():
        ad = asdict(a)
        edges.append(
            {
                "id": f"member_of:{ad.get('agent_type')}:{ad.get('post_id')}",
                "source": ad.get("agent_type"),
                "target": ad.get("post_id"),
                "relation": "member_of",
                "weight": 1.0,
            }
        )

    # Edges: knowledge_edges (optional, capped)
    if include_edges and getattr(runtime, "knowledge_edges", None) is not None and max_edges > 0:
        try:
            from probos.knowledge.edges import KnowledgeRelationType
            relation_filter: list[KnowledgeRelationType] | None = None
            if edge_relations:
                wanted = {r.strip() for r in edge_relations.split(",") if r.strip()}
                valid_values = {r.value for r in KnowledgeRelationType}
                relation_filter = [
                    KnowledgeRelationType(r) for r in wanted if r in valid_values
                ]
                if not relation_filter:
                    relation_filter = None
            graph_edges = await runtime.knowledge_edges.find_edges(limit=max_edges)
            for ke in graph_edges:
                if relation_filter is not None and ke.relation not in relation_filter:
                    continue
                edges.append(
                    {
                        "id": ke.id,
                        "source": ke.source_id,
                        "target": ke.target_id,
                        "relation": ke.relation.value,
                        "weight": ke.weight,
                        "confidence": ke.confidence,
                        "source_type": ke.source_type.value,
                        "target_type": ke.target_type.value,
                    }
                )
        except Exception as exc:  # noqa: BLE001 — tier-2 log-and-degrade
            logger.warning("AD-520: knowledge_edges.find_edges failed: %s", exc)

    # Truncate combined node list
    if max_nodes > 0 and len(nodes) > max_nodes:
        nodes = nodes[:max_nodes]

    return {
        "nodes": nodes,
        "edges": edges,
        "generated_at": _time.time(),
    }


@router.get("/spatial-layout")
async def get_spatial_layout(runtime: Any = Depends(get_runtime)) -> Any:
    """AD-520: Spatial Knowledge Explorer — deck topology snapshot."""
    layout = getattr(runtime, "spatial_layout", None)
    if layout is None:
        return JSONResponse(
            {"error": "Spatial explorer not enabled"}, status_code=503
        )
    return layout.to_dict()


@router.get("/skills/{agent_type}")
async def get_ontology_skills(agent_type: str, runtime: Any = Depends(get_runtime)) -> Any:
    """Agent's skill context — role template, current profile, qualification status."""
    if not runtime.ontology:
        return JSONResponse({"error": "Ontology not initialized"}, status_code=503)

    role_template = runtime.ontology.get_role_template_for_agent(agent_type)
    result: dict[str, Any] = {"agent_type": agent_type}

    if role_template:
        result["role_template"] = {
            "post_id": role_template.post_id,
            "required": [
                {"skill_id": r.skill_id, "min_proficiency": r.min_proficiency}
                for r in role_template.required_skills
            ],
            "optional": [
                {"skill_id": o.skill_id, "min_proficiency": o.min_proficiency}
                for o in role_template.optional_skills
            ],
        }
    else:
        result["role_template"] = None

    # Include current skill profile if available
    if runtime.skill_service:
        assignment = runtime.ontology.get_assignment_for_agent(agent_type)
        if assignment and assignment.agent_id:
            profile = await runtime.skill_service.get_profile(assignment.agent_id)
            if profile:
                result["profile"] = profile.to_dict()

    # Include qualification paths
    result["qualification_paths"] = [
        {
            "path_id": f"{qp.from_rank}_to_{qp.to_rank}",
            "description": qp.description,
            "requirements": [
                {"type": r.type, "description": r.description,
                 "min_proficiency": r.min_proficiency, "scope": r.scope,
                 "min_count": r.min_count}
                for r in qp.requirements
            ],
        }
        for qp in runtime.ontology.get_all_qualification_paths()
    ]

    return result


@router.get("/operations")
async def get_ontology_operations(runtime: Any = Depends(get_runtime)) -> Any:
    """Operations domain — standing order tiers, watch types, alert procedures, duties."""
    if not runtime.ontology:
        return JSONResponse({"error": "Ontology not initialized"}, status_code=503)
    ont = runtime.ontology
    return {
        "standing_order_tiers": [asdict(t) for t in ont.get_standing_order_tiers()],
        "watch_types": [asdict(w) for w in ont.get_watch_types()],
        "alert_procedures": {k: asdict(v) for k, v in ont._alert_procedures.items()},
        "duty_categories": [asdict(d) for d in ont.get_duty_categories()],
    }


@router.get("/communication")
async def get_ontology_communication(runtime: Any = Depends(get_runtime)) -> Any:
    """Communication domain — channel types, thread modes, message patterns."""
    if not runtime.ontology:
        return JSONResponse({"error": "Ontology not initialized"}, status_code=503)
    ont = runtime.ontology
    return {
        "channel_types": [asdict(c) for c in ont.get_channel_types()],
        "thread_modes": [asdict(t) for t in ont.get_thread_modes()],
        "message_patterns": [asdict(m) for m in ont.get_message_patterns()],
    }


@router.get("/resources")
async def get_ontology_resources(runtime: Any = Depends(get_runtime)) -> Any:
    """Resources domain — model tiers, tool capabilities, knowledge sources."""
    if not runtime.ontology:
        return JSONResponse({"error": "Ontology not initialized"}, status_code=503)
    ont = runtime.ontology
    return {
        "model_tiers": [asdict(m) for m in ont.get_model_tiers()],
        "tool_capabilities": [asdict(t) for t in ont.get_tool_capabilities()],
        "knowledge_sources": [asdict(k) for k in ont.get_knowledge_sources()],
    }


@router.get("/records")
async def get_ontology_records(runtime: Any = Depends(get_runtime)) -> Any:
    """Records domain — knowledge tiers, classifications, document classes, retention."""
    if not runtime.ontology:
        return JSONResponse({"error": "Ontology not initialized"}, status_code=503)
    ont = runtime.ontology
    return {
        "knowledge_tiers": [asdict(kt) for kt in ont.get_knowledge_tiers()],
        "classifications": [asdict(c) for c in ont.get_classifications()],
        "document_classes": [asdict(dc) for dc in ont.get_document_classes()],
        "retention_policies": [asdict(rp) for rp in ont.get_retention_policies()],
        "repository_structure": [asdict(d) for d in ont.get_repository_structure()],
    }
