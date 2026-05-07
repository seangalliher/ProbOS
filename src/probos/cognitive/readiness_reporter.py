"""AD-628f: Ship-wide and per-department readiness reporter.

Pure read-side aggregator over AD-628b AgentSkillReadinessProfile +
ontology assignments + active agent registry.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from probos.skill_framework import ProficiencyLevel

if TYPE_CHECKING:
    from probos.cognitive.skill_readiness import AgentSkillReadinessService


CRating = Literal["C1", "C2", "C3", "C4"]


@dataclass(frozen=True)
class DepartmentReadinessReport:
    """AD-628f: per-department readiness snapshot."""

    department: str
    member_count: int
    qualified_skill_coverage: float
    proficiency_mean: float
    regression_count_24h: int
    decay_count_24h: int


@dataclass(frozen=True)
class ShipReadinessReport:
    """AD-628f: ship-wide readiness snapshot."""

    captured_at: float
    departments: list[DepartmentReadinessReport] = field(default_factory=list)
    composite_score: float = 0.0
    c_rating: CRating = "C4"


def _to_c_rating(score: float) -> CRating:
    if score >= 0.85:
        return "C1"
    if score >= 0.70:
        return "C2"
    if score >= 0.50:
        return "C3"
    return "C4"


class ReadinessReporter:
    """AD-628f: read-side ship readiness aggregator."""

    def __init__(
        self,
        readiness_service: "AgentSkillReadinessService",
        ontology: Any,
        agent_registry: Any,
        *,
        skill_registry: Any | None = None,
    ) -> None:
        self._readiness = readiness_service
        self._ontology = ontology
        self._registry = agent_registry
        self._skill_registry = skill_registry

    def _expected_skill_count_for_department(self, department: str) -> int:
        """Heuristic floor for expected skill coverage.

        Uses skill registry domain filter when available; falls back to a
        baseline of 1 (so coverage = qualifications / max(1, expected)).
        """
        if self._skill_registry is None:
            return 1
        try:
            skills = self._skill_registry.list_skills(domain=department)
            return max(1, len(skills))
        except Exception:
            return 1

    def _agent_ids_for_department(self, department: str) -> list[str]:
        """Return active agent ids in the given department."""
        result: list[str] = []
        try:
            assignments = self._ontology.get_all_assignments() if self._ontology else []
        except Exception:
            assignments = []
        agent_types_in_dept: set[str] = set()
        for a in assignments:
            try:
                agent_dept = self._ontology.get_agent_department(a.agent_type)
            except Exception:
                agent_dept = None
            if agent_dept == department:
                agent_types_in_dept.add(a.agent_type)
        try:
            all_agents = self._registry.all() if self._registry else []
        except Exception:
            all_agents = []
        for agent in all_agents:
            atype = getattr(agent, "agent_type", None)
            if atype in agent_types_in_dept:
                result.append(getattr(agent, "id", ""))
        return [aid for aid in result if aid]

    async def compute_department_readiness(
        self, department: str,
    ) -> DepartmentReadinessReport:
        """Aggregate readiness across active crew in one department."""
        agent_ids = self._agent_ids_for_department(department)
        if not agent_ids:
            return DepartmentReadinessReport(
                department=department,
                member_count=0,
                qualified_skill_coverage=0.0,
                proficiency_mean=0.0,
                regression_count_24h=0,
                decay_count_24h=0,
            )

        expected = self._expected_skill_count_for_department(department)
        cutoff = time.time() - 86400.0

        coverage_terms: list[float] = []
        proficiency_values: list[int] = []
        regression_count = 0
        decay_count = 0

        for aid in agent_ids:
            profile = await self._readiness.get_profile(aid)
            coverage_terms.append(len(profile.qualifications) / float(expected))
            for level_name, count in profile.proficiency_distribution.items():
                try:
                    level_value = ProficiencyLevel[level_name].value
                except KeyError:
                    continue
                proficiency_values.extend([level_value] * count)
            for r in profile.recent_regressions:
                if r.timestamp >= cutoff:
                    regression_count += 1
                    if "decay" in (r.reason or "").lower():
                        decay_count += 1

        coverage_mean = sum(coverage_terms) / len(coverage_terms) if coverage_terms else 0.0
        proficiency_mean = (
            sum(proficiency_values) / len(proficiency_values)
            if proficiency_values else 0.0
        )

        return DepartmentReadinessReport(
            department=department,
            member_count=len(agent_ids),
            qualified_skill_coverage=coverage_mean,
            proficiency_mean=proficiency_mean,
            regression_count_24h=regression_count,
            decay_count_24h=decay_count,
        )

    async def compute_ship_readiness(self) -> ShipReadinessReport:
        """Aggregate readiness across all departments."""
        captured_at = time.time()
        departments: list[str] = []
        try:
            for d in (self._ontology.get_departments() if self._ontology else []):
                name = getattr(d, "name", None) or getattr(d, "id", None)
                if name:
                    departments.append(name)
        except Exception:
            departments = []

        reports: list[DepartmentReadinessReport] = []
        for dept_name in departments:
            reports.append(await self.compute_department_readiness(dept_name))

        total_members = sum(r.member_count for r in reports)
        if total_members > 0:
            # Member-count-weighted mean of (coverage + proficiency-fraction) / 2.
            # Proficiency normalized against ProficiencyLevel.SHAPE.value (7).
            shape_value = ProficiencyLevel.SHAPE.value
            score_sum = 0.0
            for r in reports:
                normalized_proficiency = r.proficiency_mean / shape_value if shape_value else 0.0
                dept_score = (r.qualified_skill_coverage + normalized_proficiency) / 2.0
                score_sum += dept_score * r.member_count
            composite = score_sum / total_members
        else:
            composite = 0.0

        composite = max(0.0, min(1.0, composite))
        c_rating: CRating = _to_c_rating(composite)

        return ShipReadinessReport(
            captured_at=captured_at,
            departments=reports,
            composite_score=composite,
            c_rating=c_rating,
        )
