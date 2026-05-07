"""SoftwareEngineer specialty router — pure helper for chunk/spec routing (AD-476).

This module ships the routing primitives consumed by AD-546 (SWE Tool Harness
pipeline integration). v1 ships zero production-path callers — the helpers are
exported for downstream ADs and exercised by tests.

Architecture (AD-476):

    BuildSpec / ChunkSpec
        ↓
    SpecialistRouter.route_*  (pure rule-set scoring on target_file paths)
        ↓
    SpecialtyMatchResult(specialty, score, rationale)

Five specialties + GENERAL fallback:

    BACKEND        — Python, FastAPI, database, API design
    FRONTEND       — React, TypeScript, CSS, UI components
    TEST           — pytest, fixtures, edge cases
    INFRASTRUCTURE — Docker, CI/CD, config, deployment
    DATA           — schemas, migrations, pipelines, query optimization
    GENERAL        — fallback when no specialty rule set scores above 0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.cognitive.builder import BuildSpec, ChunkSpec


logger = logging.getLogger(__name__)


class SoftwareEngineerSpecialty(str, Enum):
    """Five specialty domains + GENERAL fallback for SWE crew routing (AD-476)."""

    GENERAL = "general"
    BACKEND = "backend"
    FRONTEND = "frontend"
    TEST = "test"
    INFRASTRUCTURE = "infrastructure"
    DATA = "data"


@dataclass(frozen=True)
class SpecialtyMatchResult:
    """Result of a specialty routing decision.

    Frozen — the decision is a snapshot of the inputs at routing time and
    callers should not mutate it. Rationale is human-readable for log lines
    and is consumed by the per-AD test plan.
    """

    specialty: SoftwareEngineerSpecialty
    score: int
    rationale: str

    def to_dict(self) -> dict:
        return {
            "specialty": self.specialty.value,
            "score": self.score,
            "rationale": self.rationale,
        }


# Rule sets are (substring | suffix, weight) tuples evaluated against each
# target_file path. Suffix rules use ``.endswith``; substring rules use
# ``in path``. Weights sum across all matching rules. Highest-scoring
# specialty wins; ties resolve in declaration order via the rule-set list.
#
# Engineering Principle DRY: rule sets live in one place; both
# ``route_build_spec`` and ``route_chunk`` consume them via ``score_path``.

_SUFFIX_RULES: dict[SoftwareEngineerSpecialty, tuple[tuple[str, int], ...]] = {
    SoftwareEngineerSpecialty.FRONTEND: (
        (".tsx", 3), (".ts", 2), (".jsx", 3), (".js", 1),
        (".css", 2), (".scss", 2), (".html", 2),
    ),
    SoftwareEngineerSpecialty.TEST: (
        (".py", 0),  # placeholder — TEST scoring is path-based, not suffix-based
    ),
    SoftwareEngineerSpecialty.INFRASTRUCTURE: (
        (".yml", 2), (".yaml", 2), (".toml", 1),
    ),
    SoftwareEngineerSpecialty.DATA: (
        (".sql", 3),
    ),
    SoftwareEngineerSpecialty.BACKEND: (
        (".py", 1),
    ),
}

_SUBSTRING_RULES: dict[SoftwareEngineerSpecialty, tuple[tuple[str, int], ...]] = {
    SoftwareEngineerSpecialty.FRONTEND: (
        ("/ui/", 3), ("ui/src/", 3), ("/components/", 2),
        ("/store/", 1), ("/__tests__/", -2),  # frontend tests rerouted to TEST below
    ),
    SoftwareEngineerSpecialty.TEST: (
        ("tests/", 4), ("/test_", 3), ("conftest", 3), ("__tests__/", 4),
    ),
    SoftwareEngineerSpecialty.INFRASTRUCTURE: (
        ("Dockerfile", 4), ("docker-compose", 4), (".github/workflows/", 3),
        ("config/", 2), ("scripts/launch", 2), ("/ci/", 2),
    ),
    SoftwareEngineerSpecialty.DATA: (
        ("migrations/", 4), ("schemas/", 3), ("/db/", 2),
    ),
    SoftwareEngineerSpecialty.BACKEND: (
        ("routers/", 2), ("/api.py", 3), ("/services/", 1), ("/cognitive/", 1),
    ),
}


def score_path(path: str) -> dict[SoftwareEngineerSpecialty, int]:
    """Return the per-specialty score breakdown for a single path.

    Pure function — used by both ``SpecialistRouter`` methods and exposed for
    test introspection. A path that scores 0 across all specialties resolves
    to ``GENERAL`` at the caller layer (this helper does not invent a
    GENERAL score; it is the absence of any other signal).
    """

    scores: dict[SoftwareEngineerSpecialty, int] = {
        s: 0 for s in SoftwareEngineerSpecialty
    }
    p = path.replace("\\", "/")  # Windows path normalisation

    for specialty, suffixes in _SUFFIX_RULES.items():
        for suffix, weight in suffixes:
            if p.endswith(suffix) and weight > 0:
                scores[specialty] += weight

    for specialty, substrings in _SUBSTRING_RULES.items():
        for needle, weight in substrings:
            if needle in p:
                scores[specialty] += weight

    return scores


class SpecialistRouter:
    """Pure routing helper — no runtime dependency, no LLM call, no global state.

    Constructor takes no arguments; the rule sets are module-level constants
    so subclassing for an out-of-repo overlay can override either the
    constants (via subclass module re-import) or the routing methods directly.

    Engineering Principle SOLID-S: single responsibility — turn paths into a
    specialty decision. Engineering Principle Open/Closed: extension via
    subclassing or module-level rule-set replacement.
    """

    def __init__(self) -> None:
        return

    def route_build_spec(self, spec: BuildSpec) -> SpecialtyMatchResult:
        """Score a BuildSpec across its target_files; return the winner.

        Aggregates ``score_path`` results across every entry in
        ``spec.target_files``. Test files in ``spec.test_files`` count
        toward the TEST specialty (read at AD-546 dispatch time as
        "this build needs a test specialist for the test files").

        Rationale string lists the top three contributing path/specialty
        pairs for log-line traceability.
        """

        return self._score_paths(
            paths=list(spec.target_files) + list(getattr(spec, "test_files", []) or []),
            label=getattr(spec, "title", "build_spec"),
        )

    def route_chunk(self, chunk: ChunkSpec) -> SpecialtyMatchResult:
        """Score a ChunkSpec on its single target_file.

        ChunkSpec has exactly one ``target_file`` field; routing is a single
        ``score_path`` invocation followed by argmax + rationale assembly.
        """

        return self._score_paths(
            paths=[chunk.target_file],
            label=getattr(chunk, "chunk_id", "chunk"),
        )

    def _score_paths(self, *, paths: list[str], label: str) -> SpecialtyMatchResult:
        """Argmax across paths; tie-break on declaration order."""

        aggregate: dict[SoftwareEngineerSpecialty, int] = {
            s: 0 for s in SoftwareEngineerSpecialty
        }
        contributions: list[tuple[str, SoftwareEngineerSpecialty, int]] = []

        for path in paths:
            per_path = score_path(path)
            for specialty, score in per_path.items():
                aggregate[specialty] += score
                if score > 0:
                    contributions.append((path, specialty, score))

        # Argmax over non-GENERAL specialties; GENERAL is the fallback when
        # every other specialty scores zero or negative.
        best = SoftwareEngineerSpecialty.GENERAL
        best_score = 0
        for specialty in (
            SoftwareEngineerSpecialty.BACKEND,
            SoftwareEngineerSpecialty.FRONTEND,
            SoftwareEngineerSpecialty.TEST,
            SoftwareEngineerSpecialty.INFRASTRUCTURE,
            SoftwareEngineerSpecialty.DATA,
        ):
            if aggregate[specialty] > best_score:
                best = specialty
                best_score = aggregate[specialty]

        # Build human-readable rationale: top 3 contributions to the winner
        # (or "no specialty signal — defaulting to general" when GENERAL).
        if best is SoftwareEngineerSpecialty.GENERAL:
            rationale = f"{label}: no specialty signal — defaulting to general"
        else:
            best_contribs = sorted(
                (c for c in contributions if c[1] is best),
                key=lambda c: c[2],
                reverse=True,
            )[:3]
            joined = ", ".join(f"{path}(+{score})" for path, _, score in best_contribs)
            rationale = f"{label}: routed to {best.value} via {joined}"

        logger.info(
            "AD-476 SpecialistRouter: %s → %s (score=%d)",
            label, best.value, best_score,
        )
        return SpecialtyMatchResult(specialty=best, score=best_score, rationale=rationale)
