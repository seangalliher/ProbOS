"""Explicit first-person projections of stored wellness and effective authority."""

from __future__ import annotations

import logging
import math
import time
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Protocol

from probos.config import format_trust
from probos.tools.protocol import ToolPermission

if TYPE_CHECKING:
    from probos.cognitive.agentic_dispatch import AgentIdentityRegistry, AgentIdentityTrust
    from probos.cognitive.counselor import CognitiveProfile
    from probos.ontology.models import Post
    from probos.tools.protocol import ToolRegistration

logger = logging.getLogger(__name__)

_ENTRY_LIMIT = 25
_TEXT_LIMIT = 256
_CONCERN_LIMIT = 3
_OPTIONAL_ENTRIES = (
    ("authority", "held"), ("authority", "withheld"), ("wellness", "concerns"),
)


class CounselorReader(Protocol):
    def get_profile(self, agent_id: str) -> CognitiveProfile | None: ...


class CounselorRegistry(Protocol):
    def get_by_pool(self, pool_name: str) -> list[CounselorReader]: ...


class AuthorityOntology(Protocol):
    def get_agent_department(self, agent_type: str) -> str | None: ...

    def get_post_for_agent(self, agent_type: str) -> Post | None: ...

    def get_chain_of_command(self, post_id: str) -> list[Post]: ...


class PermissionReader(Protocol):
    def list_tools(self, *, enabled_only: bool = True) -> list[ToolRegistration]: ...

    def resolve_permission(
        self, agent_id: str, tool_id: str, *,
        agent_department: str | None = None, agent_rank: str = "ensign",
    ) -> ToolPermission: ...


class _SampledTrust:
    def __init__(self, source: AgentIdentityTrust) -> None:
        self._source = source
        self.sample: float | None = None

    def get_score(self, agent_id: str) -> float:
        score = self._source.get_score(agent_id)
        if type(score) not in (int, float) or not math.isfinite(score):
            raise ValueError("Invalid authority trust sample")
        self.sample = score
        return score


def collect_wellness_state(
    agent_id: str, *, registry: CounselorRegistry | None,
) -> dict[str, Any]:
    """Read only the subject's stored clinical whitelist, never a new assessment."""
    if type(agent_id) is not str or not agent_id.strip() or registry is None:
        return {}
    try:
        counselors = registry.get_by_pool("counselor")
        if not counselors or not callable(getattr(counselors[0], "get_profile", None)):
            return {}
        profile = counselors[0].get_profile(agent_id)
        if profile is None:
            return {}
        result: dict[str, Any] = {
            "alert_level": profile.alert_level,
            "confabulation_rate": format_trust(profile.confabulation_rate),
            "memory_integrity_score": format_trust(profile.memory_integrity_score),
        }
        assessment = profile.latest_assessment()
        if assessment is None:
            return result
        # Recommendations and notes advise the Captain, not the assessed subject.
        for key in ("wellness_score", "trust_drift", "confidence_drift", "hebbian_drift"):
            result[key] = format_trust(getattr(assessment, key))
        result["fit_for_duty"] = assessment.fit_for_duty
        concerns = assessment.concerns
        if type(concerns) is not list or any(type(text) is not str for text in concerns):
            raise ValueError("Invalid stored wellness concerns")
        result["concerns"] = concerns[:_CONCERN_LIMIT]
        result["coverage"] = {
            "concerns_total": len(concerns),
            "concerns_omitted": len(concerns) - len(result["concerns"]),
            "concern_characters_omitted": (
                sum(map(len, concerns)) - sum(map(len, result["concerns"]))
            ),
        }
        result["trust_drift_trend"] = format_trust(profile.drift_trend("trust_drift"))
        timestamp = assessment.timestamp
        if type(timestamp) in (int, float) and math.isfinite(timestamp):
            result["assessed_at"] = timestamp
        result = filter_optional_domains({"wellness": result})["wellness"]
        result["concerns"] = [text[:_TEXT_LIMIT] for text in result["concerns"]]
        coverage = result["coverage"]
        coverage["concern_characters_omitted"] = (
            sum(map(len, concerns)) - sum(map(len, result["concerns"]))
        )
        coverage["complete"] = (
            coverage["concerns_omitted"] == 0
            and coverage["concern_characters_omitted"] == 0
        )
        return result
    except Exception:
        logger.warning(
            "Stored wellness read failed; the subject's assessment is unknown, "
            "returning no clinical projection"
        )
        return {}


def _escalation_route(
    ontology: AuthorityOntology, agent_type: str, department: str,
) -> str:
    try:
        post = ontology.get_post_for_agent(agent_type)
        if post is None:
            return "Captain"
        subordinate_ids = {post.id}
        for superior in ontology.get_chain_of_command(post.id):
            if superior.id in subordinate_ids:
                continue
            if (
                superior.department_id == department
                and subordinate_ids.intersection(superior.authority_over)
            ):
                title = superior.title
                return (
                    title if type(title) is str and title.strip()
                    and len(title) <= _TEXT_LIMIT else "Captain"
                )
            subordinate_ids.add(superior.id)
    except Exception:
        logger.warning(
            "Authority route lookup failed; a departmental billet is unknown, "
            "using Captain guidance without changing permissions"
        )
    return "Captain"


def collect_authority_state(
    agent_id: str, *, agent_registry: AgentIdentityRegistry | None,
    ontology: AuthorityOntology | None, trust_network: AgentIdentityTrust | None,
    tool_registry: PermissionReader | None,
) -> dict[str, Any]:
    """Project the enabled registry using the execution identity and permissions."""
    from probos.cognitive.agentic_dispatch import resolve_agentic_identity

    try:
        if tool_registry is None or trust_network is None:
            raise ValueError("Missing authority service")
        sampled_trust = _SampledTrust(trust_network)
        identity = resolve_agentic_identity(
            agent_id=agent_id, agent_registry=agent_registry,
            ontology=ontology, trust_network=sampled_trust,
        )
        if ontology is None or sampled_trust.sample is None:
            raise ValueError("Missing resolved authority")
        catalog = tool_registry.list_tools(enabled_only=True)
        if type(catalog) is not list:
            raise ValueError("Invalid enabled catalog")
    except Exception:
        logger.warning(
            "Authority identity or catalog read failed; permissions are unknown, "
            "returning no authority projection"
        )
        return {}

    held: list[dict[str, str]] = []
    withheld: list[str] = []
    held_total = withheld_total = unresolved_total = 0
    for registration in catalog:
        try:
            tool_id = registration.tool_id
            if type(tool_id) is not str or not tool_id:
                raise ValueError("Invalid registered tool identity")
            permission = tool_registry.resolve_permission(
                agent_id, tool_id, agent_department=identity.department,
                agent_rank=identity.rank,
            )
            if not isinstance(permission, ToolPermission):
                raise ValueError("Invalid effective permission")
        except Exception:
            unresolved_total += 1
            continue
        if permission is ToolPermission.NONE:
            withheld_total += 1
            if len(withheld) < _ENTRY_LIMIT and len(tool_id) <= _TEXT_LIMIT:
                withheld.append(tool_id)
        else:
            held_total += 1
            if len(held) < _ENTRY_LIMIT and len(tool_id) <= _TEXT_LIMIT:
                held.append({"tool_id": tool_id, "permission": permission.value})

    resolved_total = held_total + withheld_total
    if unresolved_total:
        logger.warning(
            "Authority permission resolution failed for %s of %s enabled tools; "
            "coverage is uncertain, returning only resolved facts",
            unresolved_total, len(catalog),
        )
        if not resolved_total:
            return {}
    result = {
        "department": identity.department,
        "rank": identity.rank,
        "trust_score": format_trust(sampled_trust.sample),
        "held": held,
        "withheld": withheld,
        "escalation_route": _escalation_route(
            ontology, identity.agent_type, identity.department,
        ),
        "coverage": {
            "population": "registered_enabled_tools",
            "catalog_total": len(catalog),
            "resolved_total": resolved_total,
            "unresolved_total": unresolved_total,
            "held_total": held_total,
            "withheld_total": withheld_total,
            "held_omitted": held_total - len(held),
            "withheld_omitted": withheld_total - len(withheld),
            "complete": (
                unresolved_total == 0
                and held_total == len(held) and withheld_total == len(withheld)
            ),
        },
    }
    return filter_optional_domains({"authority": result})["authority"]


def _omit_optional_entry(projection: dict[str, Any], key: str, index: int) -> None:
    removed = projection[key].pop(index)
    coverage = projection["coverage"]
    coverage[f"{key}_omitted"] += 1
    coverage["complete"] = False
    if key == "concerns":
        coverage["concern_characters_omitted"] += len(removed)


def filter_optional_domains(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Copy optional projections and omit whole matching entries, never source data."""
    from probos.cognitive.decomposer import is_capability_gap

    filtered = dict(snapshot)
    for domain in ("wellness", "authority"):
        if domain in filtered:
            filtered[domain] = deepcopy(filtered[domain])
    for domain, key in _OPTIONAL_ENTRIES:
        projection = filtered.get(domain) or {}
        entries = projection.get(key, [])
        for index in range(len(entries) - 1, -1, -1):
            entry = entries[index]
            text = (
                f"{entry['tool_id']} ({entry['permission']})" if key == "held" else entry
            )
            if is_capability_gap(text) or is_capability_gap(str(entry)):
                _omit_optional_entry(projection, key, index)
    wellness = filtered.get("wellness") or {}
    if "coverage" in wellness:
        coverage = wellness["coverage"]
        coverage["complete"] = (
            coverage.get("complete", True)
            and coverage["concerns_omitted"] == 0
            and coverage["concern_characters_omitted"] == 0
        )
    return filtered


def render_optional_domains(snapshot: dict[str, Any]) -> list[str]:
    """Render explicit projections without changing the five operational blocks."""
    if not any(snapshot.get(domain) for domain in ("wellness", "authority")):
        return []
    from probos.cognitive.decomposer import is_capability_gap

    snapshot = filter_optional_domains(snapshot)
    optional = {
        domain: snapshot[domain] for domain in ("wellness", "authority") if domain in snapshot
    }
    if is_capability_gap(str(optional)):
        raise ValueError("Optional telemetry presentation check failed.")
    lines: list[str] = []
    omitted = False
    wellness = snapshot.get("wellness") or {}
    if wellness:
        parts = [
            f"{key}: {wellness[key]}" for key in (
                "wellness_score", "fit_for_duty", "alert_level", "trust_drift",
                "confidence_drift", "hebbian_drift", "confabulation_rate",
                "memory_integrity_score", "trust_drift_trend",
            ) if key in wellness
        ]
        timestamp = wellness.get("assessed_at")
        now = time.time()
        age = "unknown"
        if (
            type(timestamp) in (int, float) and math.isfinite(timestamp)
            and 0 < timestamp <= now
        ):
            age = f"{format_trust((now - timestamp) / 3600)}h"
        parts.append(f"assessment age: {age}")
        lines.append(f"Wellness: {' | '.join(parts)}")
        if "concerns" in wellness:
            coverage = wellness["coverage"]
            concerns = wellness["concerns"]
            lines.append(
                f"Concerns: {concerns}" if concerns else
                f"Concerns: 0 shown; {coverage['concerns_omitted']} omitted"
            )
            lines.append(
                f"Concern coverage: total={coverage['concerns_total']}; "
                f"omitted={coverage['concerns_omitted']}; "
                f"characters omitted={coverage['concern_characters_omitted']}; "
                f"complete={coverage['complete']}"
            )
            omitted = (
                coverage["concerns_omitted"] > 0
                or coverage["concern_characters_omitted"] > 0
            )
    authority = snapshot.get("authority") or {}
    if authority:
        lines.append(
            f"Authority: department={authority['department']}; "
            f"rank={authority['rank']}; trust={authority['trust_score']}"
        )
        held = ", ".join(
            f"{entry['tool_id']} ({entry['permission']})" for entry in authority["held"]
        )
        coverage = authority["coverage"]
        lines.append(
            f"Held: {held}" if held else
            f"Held: 0 shown; {coverage['held_omitted']} omitted"
        )
        withheld = ", ".join(authority["withheld"])
        lines.append(
            f"Withheld: {withheld}" if withheld else
            f"Withheld: 0 shown; {coverage['withheld_omitted']} omitted"
        )
        lines.append(
            f"Escalation route: {authority['escalation_route']} "
            "(guidance only; permissions unchanged)"
        )
        lines.append(
            f"Authority coverage: population={coverage['population']}; "
            f"catalog={coverage['catalog_total']}; resolved={coverage['resolved_total']}; "
            f"unresolved={coverage['unresolved_total']}; "
            f"held total={coverage['held_total']}; withheld total={coverage['withheld_total']}; "
            f"held omitted={coverage['held_omitted']}; "
            f"withheld omitted={coverage['withheld_omitted']}; complete={coverage['complete']}"
        )
        omitted = omitted or coverage["held_omitted"] > 0 or coverage["withheld_omitted"] > 0
    if omitted:
        lines.append(
            "Presentation omissions: valid source information is absent from this "
            "projection; counts do not restore it. "
            "No alternative retrieval mechanism is promised."
        )
    if is_capability_gap("\n".join(lines)):
        raise ValueError("Optional telemetry presentation check failed.")
    return lines


def prune_optional_entry(snapshot: dict[str, Any]) -> bool:
    """Remove one whole retained entry, recording omissions without recollection."""
    candidates: list[tuple[int, str, str, int]] = []
    for domain, key in _OPTIONAL_ENTRIES:
        for index, entry in enumerate(snapshot.get(domain, {}).get(key, [])):
            candidates.append((len(str(entry)), domain, key, index))
    if not candidates:
        return False
    _, domain, key, index = max(candidates)
    _omit_optional_entry(snapshot[domain], key, index)
    return True
