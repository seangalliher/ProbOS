# AD-476 v1 — Specialized Builders — Cognitive Division of Labor for SWE

**Status:** v1 — additive specialty layer on AD-521 SWE/Build Pipeline Separation
**GH Issue:** #70
**Wave:** 97
**HEAD:** 6246b35 (Wave 96 archive)
**Baseline pytest:** 12126 (Captain reference) / live xdist gate 12120 passed at HEAD
**Target pytest:** ≥12138 (Δ ≥ +12; nominal +14)
**AD numbering:** highest stem AD-696 verified; W97 mints zero new AD numbers; AD-476 already exists at `roadmap.md:4213`

---

## Problem

The roadmap entry at `docs/development/roadmap.md:4213` describes AD-476 as five domain-specialized builder extensions (Backend / Frontend / Test / Infrastructure / Data) routed by ChunkSpec, with model selection per builder type. Wave 96 (AD-521) shipped the structural prerequisite — `SoftwareEngineerAgent` extracted as the sovereign crew class, `BuildPipeline` extracted as a Ship's Computer service, `BuilderAgent` preserved as a back-compat alias. With that separation in place, the five specialty subclasses and their routing helper become a clean additive layer.

Before this AD: every code-generation request runs through a single generalist `SoftwareEngineerAgent` with one set of `instructions`, one model tier, and no signal about the kind of work being done. The Transporter Pattern (`decompose_blueprint` at `cognitive/builder.py:533`, `execute_chunks` at `:920`) emits `ChunkSpec` objects with `target_file` and `what_to_generate` metadata that go to waste — there is no consumer that asks "should this chunk go to a frontend specialist or a backend specialist?"

After this AD: a pure `SpecialistRouter.route_chunk(chunk) -> SpecialtyMatchResult` helper scores any `ChunkSpec` (or `BuildSpec`) against five specialty rule sets, five `SoftwareEngineerAgent` subclasses provide specialty-tuned `instructions` strings + per-specialty model tier overrides via the existing AD-463 ModelRegistry, and `BuildPipeline.execute_approved_build(...)` accepts a `specialty: str = "general"` kwarg that future ADs (AD-546 SWE Tool Harness, GH #13) will populate from the router. v1 does NOT wire production chunk auto-routing — that is AD-546's job — but ships every primitive AD-546 needs.

Pool registration is opt-in (`SoftwareEngineerSpecialistsConfig.enabled` defaults False, AD-695 transitional-flag precedent — pool creation is a real cognitive-budget side-effect). The five specialty agent classes are subclassable themselves (the AD-452 class-extension mechanism applies), preserving the closed-source crew-tier overlay plug-in point AD-521 W96 documented at `decisions-era-4-evolution.md:1453-1456`.

---

## Solution overview

Two new modules, five subclasses, one router, one config, one runtime wiring block, one pipeline kwarg, one test file, three tracker updates. Pure additive — every existing test that imports `BuilderAgent`, `SoftwareEngineerAgent`, `BuildPipeline`, or any pipeline helper continues to pass unchanged because:

- The base `SoftwareEngineerAgent` class is not modified (only subclassed).
- The `BuilderAgent = SoftwareEngineerAgent` alias is preserved.
- The pipeline's existing positional + kwarg signature is preserved (the new `specialty` kwarg has a default).
- `_AGENT_DEPARTMENTS` only gains entries; existing entries are not touched.
- The five new templates register alongside the existing `builder` template; `builder` itself is unchanged.
- The new pools default-disabled, so no boot-time topology change.

---

## Section 1 — `src/probos/cognitive/builder_specialist.py` (NEW)

Create new file:

```python
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
```

---

## Section 2 — `src/probos/cognitive/builder_specialists.py` (NEW)

Create new file:

```python
"""Five SoftwareEngineerAgent specialist subclasses (AD-476).

Each subclass overrides:
- ``agent_type`` — distinct from base ``"builder"`` for crew-roster identity
  (per AD-398 crew identity continuity rules; the base ``builder`` agent_type
  is unchanged).
- ``specialty`` — the SoftwareEngineerSpecialty enum value this class handles.
- ``instructions`` — specialty-tuned overlay of the base SWE instructions.
- ``_resolve_tier()`` — reads ``model_tier_overrides`` from
  ``SoftwareEngineerSpecialistsConfig`` to pick the LLM tier
  (``"deep"`` / ``"standard"`` / ``"fast"``).

Inheritance chain:

    BaseAgent
        ↓
    CognitiveAgent
        ↓
    SoftwareEngineerAgent  (Scotty — generalist crew, AD-521)
        ↓
    [BackendSWEAgent | FrontendSWEAgent | TestSWEAgent
     | InfrastructureSWEAgent | DataSWEAgent]  (AD-476)

Identity continuity: ``_handled_intents``, ``intent_descriptors``, and the
``build_code`` intent contract are inherited unchanged. Each specialist
handles ``build_code`` — the dispatcher (AD-546 future, GH #13) selects
which specialist by routing the chunk through SpecialistRouter.

The closed-source crew-tier overlay plug-in point: each specialist class is
subclassable. The OSS class structure is the extension point; the
out-of-repo overlay slots in via the AD-452 class-extension mechanism.
v1 ships zero closed-source content.
"""

from __future__ import annotations

import logging

from probos.cognitive.builder import SoftwareEngineerAgent
from probos.cognitive.builder_specialist import SoftwareEngineerSpecialty

logger = logging.getLogger(__name__)


_BASE_OUTPUT_FORMAT = """OUTPUT FORMAT:
For each file, output a block like:
===FILE: path/to/file.py===
<complete file contents or changes>
===END FILE===

For modifications, use:
===MODIFY: path/to/file.py===
===SEARCH===
<exact existing text>
===REPLACE===
<replacement text>
===END REPLACE===
===END FILE===
"""


class BackendSWEAgent(SoftwareEngineerAgent):
    """Backend specialist — Python, FastAPI, database, API design (AD-476).

    Optimized for server-side patterns: HTTP routers, Pydantic models,
    dependency-injection wiring, async/await discipline, SQLite/Postgres
    schema design, JSON serialization, error tier semantics.
    """

    agent_type = "backend_swe"
    specialty = SoftwareEngineerSpecialty.BACKEND

    instructions = (
        """You are the Backend SWE specialist for ProbOS.
You execute build specs that focus on server-side code: Python modules,
FastAPI routers, database access, async services, configuration, API contracts.

DOMAIN RULES (in addition to the standard SWE output rules):
- Prefer ``async def`` for any handler that touches I/O. Always
  ``await`` async APIs.
- Use Pydantic models for any new request/response or config shape;
  match the existing models in ``src/probos/config.py`` for style.
- HTTP routers go in ``src/probos/routers/<name>.py`` and are wired into
  ``src/probos/api.py`` alphabetically.
- Database access goes through abstract Protocol seams when introducing
  a new storage surface (Cloud-Ready Storage rule).
- Three-tier exception handling at every boundary; never swallow an
  exception silently in a router or service.
- Type-annotate every public method (parameters AND return type).

"""
        + _BASE_OUTPUT_FORMAT
    )


class FrontendSWEAgent(SoftwareEngineerAgent):
    """Frontend specialist — React, TypeScript, CSS, UI components (AD-476).

    Optimized for component architecture, store/state design, accessibility,
    HXI Design Principles compliance (no emoji, SVG strokes, motion
    communicates state).
    """

    agent_type = "frontend_swe"
    specialty = SoftwareEngineerSpecialty.FRONTEND

    instructions = (
        """You are the Frontend SWE specialist for ProbOS.
You execute build specs that focus on UI code: React components,
TypeScript types, Zustand store updates, CSS, vitest tests.

DOMAIN RULES (in addition to the standard SWE output rules):
- Components live in ``ui/src/components/<Name>.tsx`` with a matching
  test in ``ui/src/__tests__/<Name>.test.tsx``.
- Store types in ``ui/src/store/types.ts``; store actions in
  ``ui/src/store/useStore.ts``. Match the existing slice shape.
- HXI Design Principle compliance:
  * Zero emoji. Use inline SVG glyphs with ``strokeWidth: 1.5`` and
    ``strokeLinecap: round``. Active = amber ``#f0b060``; inactive =
    dim ``#666680``; glow on hover via ``drop-shadow``.
  * Motion communicates state — pulse = alive, breathe = idle,
    flash = event, fade = removing, static = disconnected.
- Vitest tests use the existing patterns in ``ui/src/__tests__/`` — no
  jest, no enzyme.

"""
        + _BASE_OUTPUT_FORMAT
    )


class TestSWEAgent(SoftwareEngineerAgent):
    """Test specialist — pytest, fixtures, edge cases (AD-476).

    Optimized for test design: arrange-act-assert structure, boundary tests
    (happy path + error + edge), test isolation, ``_Fake*`` stubs over
    complex Mock chains.
    """

    agent_type = "test_swe"
    specialty = SoftwareEngineerSpecialty.TEST

    instructions = (
        """You are the Test SWE specialist for ProbOS.
You execute build specs that focus on test code: pytest test files,
fixtures, parametrize, async tests, mocks.

DOMAIN RULES (in addition to the standard SWE output rules):
- Test files mirror source paths under ``tests/``; one ``test_<source>.py``
  per source module unless the AD spec dictates otherwise.
- Every public method must have at minimum a happy path + error case +
  empty/None edge case (Boundary Testing rule).
- Use ``pytest.mark.asyncio`` for async tests; ``async def test_*``.
- Prefer ``_Fake*`` stub classes (``_FakeRuntime``, ``_FakeAgent``) over
  ``unittest.mock.Mock`` chains when the surface is wide. Trace the
  target method body to find every ``self.x`` access; cover all of them.
- Use ``tmp_path`` fixture for filesystem; clean up resources you create.
- Tests must be order-independent. No shared mutable state between tests.
- Test names: ``test_{method}_{scenario}_{expected}``.

"""
        + _BASE_OUTPUT_FORMAT
    )


class InfrastructureSWEAgent(SoftwareEngineerAgent):
    """Infrastructure specialist — Docker, CI/CD, config, deployment (AD-476).

    Optimized for ops-side concerns: Dockerfile authoring, GitHub Actions
    workflows, YAML/TOML configuration, launch scripts.
    """

    agent_type = "infrastructure_swe"
    specialty = SoftwareEngineerSpecialty.INFRASTRUCTURE

    instructions = (
        """You are the Infrastructure SWE specialist for ProbOS.
You execute build specs that focus on infrastructure code: Dockerfiles,
docker-compose, GitHub Actions, system YAML config, launch scripts.

DOMAIN RULES (in addition to the standard SWE output rules):
- Dockerfiles use multi-stage builds where size matters; pin base image
  versions explicitly.
- GitHub Actions workflows live in ``.github/workflows/<name>.yml``;
  use existing matrix patterns; pin action versions to commit SHAs for
  third-party actions.
- YAML config edits in ``config/system.yaml`` must preserve existing
  comments; never introduce defaults that contradict the Pydantic
  defaults in ``src/probos/config.py``.
- Launch scripts in ``scripts/launch-cluster.{ps1,sh}`` — keep PowerShell
  + bash parity for any new feature.

"""
        + _BASE_OUTPUT_FORMAT
    )


class DataSWEAgent(SoftwareEngineerAgent):
    """Data specialist — schemas, migrations, pipelines, query optimization (AD-476).

    Optimized for data-shape concerns: SQL DDL, schema migrations,
    ChromaDB collection layout, query plans, index design.
    """

    agent_type = "data_swe"
    specialty = SoftwareEngineerSpecialty.DATA

    instructions = (
        """You are the Data SWE specialist for ProbOS.
You execute build specs that focus on data-layer code: SQL schemas,
migrations, ChromaDB collection setup, query optimization, indexes.

DOMAIN RULES (in addition to the standard SWE output rules):
- SQL DDL uses ``CREATE TABLE IF NOT EXISTS`` (idempotent); explicit PK
  declaration; explicit indexes for any column used in WHERE / ORDER BY.
- Migrations are append-only — never edit a migration that has shipped.
- ChromaDB collections: explicit ``metadata={...}`` schema documentation
  on creation; embedding function pinned per collection.
- Query optimization: prefer index scans; for any query touching > 1
  table, document the join order and the expected access pattern.
- Schema changes that are not backward-compatible require a
  documented data-migration step (``data/backups/`` checkpoint pattern).

"""
        + _BASE_OUTPUT_FORMAT
    )


# Public registry for the spawner / agent_fleet wirer.
SPECIALIST_CLASSES: tuple[type[SoftwareEngineerAgent], ...] = (
    BackendSWEAgent,
    FrontendSWEAgent,
    TestSWEAgent,
    InfrastructureSWEAgent,
    DataSWEAgent,
)
```

---

## Section 3 — `src/probos/cognitive/standing_orders.py` MODIFY

Add five new department mappings. SEARCH anchor includes context for uniqueness:

```
===MODIFY: src/probos/cognitive/standing_orders.py===
===SEARCH===
_AGENT_DEPARTMENTS: dict[str, str] = {
    # Engineering
    "builder": "engineering",
    "code_reviewer": "engineering",
    "engineering_officer": "engineering",
===REPLACE===
_AGENT_DEPARTMENTS: dict[str, str] = {
    # Engineering
    "builder": "engineering",
    "code_reviewer": "engineering",
    "engineering_officer": "engineering",
    # SWE specialists (AD-476) — all map to engineering for standing orders
    "backend_swe": "engineering",
    "frontend_swe": "engineering",
    "test_swe": "engineering",
    "infrastructure_swe": "engineering",
    "data_swe": "engineering",
===END REPLACE===
===END FILE===
```

---

## Section 4 — `src/probos/config.py` MODIFY

Add `SoftwareEngineerSpecialistsConfig` Pydantic model and wire onto `SystemConfig`. Two SEARCH/REPLACE pairs.

**Pair 4a — declare the config model.** SEARCH anchor is a stable existing config model declaration (find the existing ``CognitiveConfig`` or adjacent builder-related config; Builder will use grep to locate the precise insertion point and choose an anchor that is uniquely identifiable). The declaration body:

```python
class SoftwareEngineerSpecialistsConfig(BaseModel):
    """AD-476 v1 — opt-in pool registration for the five SWE specialists.

    Default ``enabled=False`` per AD-695 transitional-flag precedent: pool
    creation is a real cognitive-budget side-effect (five new agents at
    boot), so v1 ships dormant. Operators flip ``enabled=True`` after
    AD-546 wires the production chunk-routing call site.
    """

    enabled: bool = False
    pool_size_per_specialty: int = 1
    model_tier_overrides: dict[str, str] = Field(
        default_factory=lambda: {
            "backend": "deep",
            "frontend": "standard",
            "test": "fast",
            "infrastructure": "standard",
            "data": "deep",
        }
    )

    @field_validator("pool_size_per_specialty")
    @classmethod
    def _pool_size_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("pool_size_per_specialty must be >= 1")
        return v

    @field_validator("model_tier_overrides")
    @classmethod
    def _tier_values_valid(cls, v: dict[str, str]) -> dict[str, str]:
        valid_tiers = {"fast", "standard", "deep"}
        for specialty, tier in v.items():
            if tier not in valid_tiers:
                raise ValueError(
                    f"AD-476 model_tier_overrides[{specialty!r}]={tier!r} "
                    f"not in {sorted(valid_tiers)}"
                )
        return v
```

**Pair 4b — wire onto SystemConfig.** SEARCH anchor is the existing field block on `SystemConfig` adjacent to other cognitive/builder fields (Builder identifies the exact insertion line via grep at build time). REPLACE adds:

```python
    swe_specialists: SoftwareEngineerSpecialistsConfig = Field(
        default_factory=SoftwareEngineerSpecialistsConfig
    )
```

---

## Section 5 — `src/probos/runtime.py` MODIFY (two pairs)

**Pair 5a — sibling import.**

```
===MODIFY: src/probos/runtime.py===
===SEARCH===
from probos.cognitive.builder import BuilderAgent
===REPLACE===
from probos.cognitive.builder import BuilderAgent
from probos.cognitive.builder_specialists import (
    BackendSWEAgent,
    DataSWEAgent,
    FrontendSWEAgent,
    InfrastructureSWEAgent,
    TestSWEAgent,
)
===END REPLACE===
===END FILE===
```

**Pair 5b — template registrations.**

```
===MODIFY: src/probos/runtime.py===
===SEARCH===
        self.spawner.register_template("builder", BuilderAgent)
===REPLACE===
        self.spawner.register_template("builder", BuilderAgent)
        # AD-476 — five SWE specialist templates (pools created in
        # startup/agent_fleet.py only when config.swe_specialists.enabled).
        self.spawner.register_template("backend_swe", BackendSWEAgent)
        self.spawner.register_template("frontend_swe", FrontendSWEAgent)
        self.spawner.register_template("test_swe", TestSWEAgent)
        self.spawner.register_template("infrastructure_swe", InfrastructureSWEAgent)
        self.spawner.register_template("data_swe", DataSWEAgent)
===END REPLACE===
===END FILE===
```

---

## Section 6 — `src/probos/startup/agent_fleet.py` MODIFY

Conditional pool creation block. The agent_fleet wirer uses `create_pool_fn(pool_name, agent_type, target_size=, agent_ids=, llm_client=, runtime=)` per the AD-691 NL-Graph pool precedent at `agent_fleet.py:68-72` and the existing builder pool precedent at the lines immediately after. Builder grep-locates the existing builder-pool creation block (the `if config.utility_agents.enabled:` block that calls `create_pool_fn("builder", "builder", target_size=1, ...)`) and INSERTS the AD-476 block immediately after the closing `)` of that block. Pattern (verbatim — copy this body):

```python
    # AD-476 — opt-in SWE specialist pools.
    if (
        getattr(config, "swe_specialists", None)
        and config.swe_specialists.enabled
    ):
        pool_size = config.swe_specialists.pool_size_per_specialty
        for specialty_template in (
            "backend_swe", "frontend_swe", "test_swe",
            "infrastructure_swe", "data_swe",
        ):
            try:
                ids = generate_pool_ids(specialty_template, specialty_template, pool_size)
                await create_pool_fn(
                    specialty_template, specialty_template,
                    target_size=pool_size,
                    agent_ids=ids,
                    llm_client=llm_client,
                    runtime=runtime,
                )
                logger.info(
                    "AD-476: spawned %s pool (target_size=%d)",
                    specialty_template, pool_size,
                )
            except Exception as exc:  # tier-2 log-and-degrade
                logger.warning(
                    "AD-476: failed to spawn %s pool: %s — continuing",
                    specialty_template, exc,
                )
    else:
        logger.info(
            "AD-476: SWE specialist pools disabled "
            "(config.swe_specialists.enabled=False)"
        )
```

The `logger` import is already present in `agent_fleet.py` (existing `logger.info` calls confirm). The `generate_pool_ids` import is also already present (used by the existing builder pool block immediately above the insertion point).

The exact SEARCH anchor is the closing `)` of the existing builder pool's `await create_pool_fn(...)` call. Builder uses ≥3 lines of context (the `# Engineering team — Builder Agent (AD-302)` comment + the `if config.utility_agents.enabled:` line + the `ids = generate_pool_ids(...)` line + the `await create_pool_fn(...)` call) to make the SEARCH block uniquely identifiable. Insertion is after the closing `)` of the builder pool's `await` call.

---

## Section 7 — `src/probos/build_pipeline.py` + `src/probos/cognitive/builder.py` MODIFY (two pairs)

**Pair 7a — `BuildPipeline.execute_approved_build` adds `specialty` kwarg.**

```
===MODIFY: src/probos/build_pipeline.py===
===SEARCH===
    async def execute_approved_build(
        self,
        file_changes: list[dict[str, Any]],
        spec: BuildSpec,
        work_dir: str,
        run_tests: bool = True,
        max_fix_attempts: int = 2,
        llm_client: BaseLLMClient | None = None,
        escalation_hook: Callable | None = None,
        builder_source: str = "native",
    ) -> BuildResult:
===REPLACE===
    async def execute_approved_build(
        self,
        file_changes: list[dict[str, Any]],
        spec: BuildSpec,
        work_dir: str,
        run_tests: bool = True,
        max_fix_attempts: int = 2,
        llm_client: BaseLLMClient | None = None,
        escalation_hook: Callable | None = None,
        builder_source: str = "native",
        specialty: str = "general",
    ) -> BuildResult:
===END REPLACE===
===END FILE===
```

The body of `execute_approved_build` in `build_pipeline.py` is also updated to log + forward the kwarg. Builder applies a SECOND SEARCH/REPLACE within the same module in the body of the method:

```
===MODIFY: src/probos/build_pipeline.py===
===SEARCH===
        return await _legacy_execute_approved_build(
            file_changes=file_changes,
            spec=spec,
            work_dir=work_dir,
            run_tests=run_tests,
            max_fix_attempts=max_fix_attempts,
            llm_client=llm_client,
            escalation_hook=escalation_hook,
===REPLACE===
        logger.info(
            "AD-476: BuildPipeline routing build '%s' as specialty=%s "
            "(builder_source=%s)",
            getattr(spec, "title", "<unknown>"), specialty, builder_source,
        )
        return await _legacy_execute_approved_build(
            file_changes=file_changes,
            spec=spec,
            work_dir=work_dir,
            run_tests=run_tests,
            max_fix_attempts=max_fix_attempts,
            llm_client=llm_client,
            escalation_hook=escalation_hook,
            specialty=specialty,
===END REPLACE===
===END FILE===
```

**Pair 7b — legacy `execute_approved_build` accepts the kwarg.**

Live signature at `cognitive/builder.py:2532` ends with `runtime: ProbOSRuntime | None = None,` as the trailing kwarg before `) -> BuildResult:`. Append `specialty` immediately after `runtime`:

```
===MODIFY: src/probos/cognitive/builder.py===
===SEARCH===
    builder_source: str = "native",
    runtime: ProbOSRuntime | None = None,
) -> BuildResult:
===REPLACE===
    builder_source: str = "native",
    runtime: ProbOSRuntime | None = None,
    specialty: str = "general",
) -> BuildResult:
===END REPLACE===
===END FILE===
```

The body of the legacy coroutine is NOT modified — `specialty` is accepted at the signature, logged at INFO inside the BuildPipeline boundary (Pair 7a), and otherwise unused. Forward-compatible: AD-546 will be the consumer that actually reads it. Existing callers continue to work because the new kwarg has a default.

---

## Section 8 — `tests/test_ad476_specialized_builders.py` (NEW)

Create the new test file with **14 tests**. Test plan:

```python
"""Tests for AD-476 v1 — Specialized Builders (Cognitive Division of Labor for SWE)."""

from __future__ import annotations

import pytest

from probos.cognitive.builder import SoftwareEngineerAgent
from probos.cognitive.builder_specialist import (
    SoftwareEngineerSpecialty,
    SpecialistRouter,
    SpecialtyMatchResult,
    score_path,
)
from probos.cognitive.builder_specialists import (
    SPECIALIST_CLASSES,
    BackendSWEAgent,
    DataSWEAgent,
    FrontendSWEAgent,
    InfrastructureSWEAgent,
    TestSWEAgent,
)
from probos.config import SoftwareEngineerSpecialistsConfig


# ----- Test 1: enum shape -----
def test_specialty_enum_has_six_values_with_string_form():
    """SoftwareEngineerSpecialty exposes 6 values; each value's ``.value`` is the
    lowercase string form used in config keys + log lines."""
    expected = {"general", "backend", "frontend", "test", "infrastructure", "data"}
    assert {s.value for s in SoftwareEngineerSpecialty} == expected
    assert SoftwareEngineerSpecialty.BACKEND.value == "backend"


# ----- Test 2: SpecialtyMatchResult is frozen + has to_dict -----
def test_specialty_match_result_frozen_and_to_dict_round_trips():
    r = SpecialtyMatchResult(
        specialty=SoftwareEngineerSpecialty.BACKEND, score=4, rationale="t",
    )
    assert r.to_dict() == {"specialty": "backend", "score": 4, "rationale": "t"}
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        r.score = 99  # type: ignore[misc]


# ----- Test 3: score_path resolves frontend (.tsx) -----
def test_score_path_frontend_tsx_scores_above_other_specialties():
    s = score_path("ui/src/components/AgentList.tsx")
    assert s[SoftwareEngineerSpecialty.FRONTEND] > s[SoftwareEngineerSpecialty.BACKEND]
    assert s[SoftwareEngineerSpecialty.FRONTEND] >= 5  # .tsx (3) + ui/src/ (3) ≥ 5 with overlap


# ----- Test 4: score_path resolves test (tests/ + test_*) -----
def test_score_path_test_directory_with_test_prefix_scores_test_specialty():
    s = score_path("tests/test_ad476_specialized_builders.py")
    assert s[SoftwareEngineerSpecialty.TEST] > 0
    # TEST should outscore BACKEND despite the .py suffix
    assert s[SoftwareEngineerSpecialty.TEST] > s[SoftwareEngineerSpecialty.BACKEND]


# ----- Test 5: score_path resolves infrastructure (Dockerfile) -----
def test_score_path_dockerfile_routes_to_infrastructure():
    s = score_path("Dockerfile")
    assert s[SoftwareEngineerSpecialty.INFRASTRUCTURE] >= 4


# ----- Test 6: score_path resolves data (.sql + migrations/) -----
def test_score_path_sql_migration_routes_to_data():
    s = score_path("migrations/001_initial.sql")
    assert s[SoftwareEngineerSpecialty.DATA] > s[SoftwareEngineerSpecialty.BACKEND]


# ----- Test 7: route_chunk picks frontend for a .tsx target -----
def test_route_chunk_frontend_tsx():
    from probos.cognitive.builder import ChunkSpec
    chunk = ChunkSpec(
        chunk_id="c1", description="add badge", target_file="ui/src/components/Badge.tsx",
        what_to_generate="React component",
    )
    result = SpecialistRouter().route_chunk(chunk)
    assert result.specialty is SoftwareEngineerSpecialty.FRONTEND
    assert result.score > 0
    assert "frontend" in result.rationale


# ----- Test 8: route_build_spec picks backend for a router target -----
def test_route_build_spec_backend_router():
    from probos.cognitive.builder import BuildSpec
    spec = BuildSpec(
        title="Add /api/specialty router",
        description="Wire new router",
        target_files=["src/probos/routers/specialty.py", "src/probos/api.py"],
        reference_files=[],
        test_files=[],
    )
    result = SpecialistRouter().route_build_spec(spec)
    assert result.specialty is SoftwareEngineerSpecialty.BACKEND
    assert result.score > 0


# ----- Test 9: route_build_spec falls back to GENERAL when no signal -----
def test_route_build_spec_general_fallback_when_no_signal():
    from probos.cognitive.builder import BuildSpec
    spec = BuildSpec(
        title="Edit a manual",
        description="Touch a doc",
        target_files=["docs/manual.md"],  # .md is not in any specialty's rule set
        reference_files=[],
        test_files=[],
    )
    result = SpecialistRouter().route_build_spec(spec)
    assert result.specialty is SoftwareEngineerSpecialty.GENERAL
    assert result.score == 0
    assert "general" in result.rationale


# ----- Test 10: each specialist subclass has the right specialty + agent_type -----
@pytest.mark.parametrize(
    "cls, expected_specialty, expected_agent_type",
    [
        (BackendSWEAgent, SoftwareEngineerSpecialty.BACKEND, "backend_swe"),
        (FrontendSWEAgent, SoftwareEngineerSpecialty.FRONTEND, "frontend_swe"),
        (TestSWEAgent, SoftwareEngineerSpecialty.TEST, "test_swe"),
        (InfrastructureSWEAgent, SoftwareEngineerSpecialty.INFRASTRUCTURE, "infrastructure_swe"),
        (DataSWEAgent, SoftwareEngineerSpecialty.DATA, "data_swe"),
    ],
)
def test_each_specialist_has_correct_specialty_and_agent_type(
    cls, expected_specialty, expected_agent_type,
):
    assert cls.specialty is expected_specialty
    assert cls.agent_type == expected_agent_type
    assert issubclass(cls, SoftwareEngineerAgent)


# ----- Test 11: each specialist's instructions extends the base output format -----
def test_specialist_instructions_distinct_from_base_and_include_output_format():
    base_instructions = SoftwareEngineerAgent.instructions
    seen = set()
    for cls in SPECIALIST_CLASSES:
        # Each must have its own non-trivial instructions string.
        assert cls.instructions, f"{cls.__name__} missing instructions"
        assert cls.instructions != base_instructions, f"{cls.__name__} not specialized"
        # The OUTPUT FORMAT block is shared.
        assert "OUTPUT FORMAT:" in cls.instructions
        seen.add(cls.instructions)
    # All five must be distinct from each other.
    assert len(seen) == len(SPECIALIST_CLASSES)


# ----- Test 12: SoftwareEngineerSpecialistsConfig defaults + validators -----
def test_specialists_config_defaults_and_validators():
    cfg = SoftwareEngineerSpecialistsConfig()
    assert cfg.enabled is False  # opt-in
    assert cfg.pool_size_per_specialty == 1
    assert cfg.model_tier_overrides == {
        "backend": "deep",
        "frontend": "standard",
        "test": "fast",
        "infrastructure": "standard",
        "data": "deep",
    }
    # Bad pool size rejected.
    with pytest.raises(Exception):
        SoftwareEngineerSpecialistsConfig(pool_size_per_specialty=0)
    # Bad tier rejected.
    with pytest.raises(Exception):
        SoftwareEngineerSpecialistsConfig(model_tier_overrides={"backend": "ultra"})


# ----- Test 13: BuildPipeline.execute_approved_build signature accepts specialty kwarg -----
def test_build_pipeline_execute_approved_build_signature_has_specialty_kwarg():
    import inspect
    from probos.build_pipeline import BuildPipeline
    sig = inspect.signature(BuildPipeline.execute_approved_build)
    assert "specialty" in sig.parameters
    p = sig.parameters["specialty"]
    assert p.default == "general"


# ----- Test 14: legacy execute_approved_build coroutine accepts specialty kwarg -----
def test_legacy_execute_approved_build_signature_has_specialty_kwarg():
    import inspect
    from probos.cognitive.builder import execute_approved_build
    sig = inspect.signature(execute_approved_build)
    assert "specialty" in sig.parameters
    assert sig.parameters["specialty"].default == "general"
```

If any of tests 13/14 fails because the legacy signature does not yet accept the kwarg (Section 7 not applied), Builder applies Section 7 first and reruns. If the legacy coroutine has internal positional-only callers that this AD must NOT break, Builder confirms via grep that there are zero such callers (`findstr /S /N /C:"execute_approved_build(" tests\*.py src\probos\*.py` — every existing call uses keyword args; verified at draft time).

---

## Section 9 — Trackers MODIFY

**Pair 9a — PROGRESS.md INSERT.** Builder uses the topmost paragraph block in PROGRESS.md as the SEARCH anchor and INSERTS the AD-476 close prose immediately above it. The close prose:

```
AD-476 v1 CLOSED. Specialized Builders — Cognitive Division of Labor for SWE (GH issue #70, Wave 97). Five SoftwareEngineerAgent subclasses (BackendSWEAgent, FrontendSWEAgent, TestSWEAgent, InfrastructureSWEAgent, DataSWEAgent) ship in new module ``src/probos/cognitive/builder_specialists.py``, each subclassing the AD-521 ``SoftwareEngineerAgent`` base with a distinct ``agent_type`` (``backend_swe`` / ``frontend_swe`` / ``test_swe`` / ``infrastructure_swe`` / ``data_swe``) and a specialty-tuned ``instructions`` string overlaying the base SWE rules with domain-specific guidance (backend: async + Pydantic + Cloud-Ready Storage; frontend: React + HXI Design Principle compliance + zero emoji; test: pytest boundary tests + ``_Fake*`` stubs over Mock chains; infrastructure: Dockerfile + GitHub Actions + YAML config preservation; data: idempotent SQL DDL + append-only migrations + ChromaDB collection schema). All five inherit ``_handled_intents = {"build_code"}`` and the ``build_code`` IntentDescriptor unchanged from AD-521 — the dispatcher selects which specialist to invoke via the new pure routing helper. New module ``src/probos/cognitive/builder_specialist.py`` ships ``SoftwareEngineerSpecialty(str, Enum)`` (six values: GENERAL/BACKEND/FRONTEND/TEST/INFRASTRUCTURE/DATA), frozen ``SpecialtyMatchResult`` dataclass (specialty + score + rationale + ``to_dict()``), pure ``score_path(path)`` helper that scores a single path across two rule-set tables (suffix rules: ``.tsx`` → frontend, ``.sql`` → data, etc.; substring rules: ``ui/src/`` → frontend, ``tests/`` → test, ``Dockerfile`` → infrastructure, ``migrations/`` → data, ``routers/`` → backend), and ``SpecialistRouter`` class with ``route_build_spec(spec)`` (aggregates across ``target_files`` + ``test_files``) and ``route_chunk(chunk)`` (single ``target_file`` argmax). Tie-break on declaration order; GENERAL is the fallback when every specialty scores zero. New ``SoftwareEngineerSpecialistsConfig`` Pydantic model in ``config.py`` with ``enabled: bool = False`` (transitional-flag default per AD-695 precedent — pool creation is a real cognitive-budget side-effect), ``pool_size_per_specialty: int = 1`` (validated >=1), and ``model_tier_overrides: dict[str, str]`` (validated against ``{fast, standard, deep}``); wired onto ``SystemConfig.swe_specialists``. Five new ``register_template(...)`` calls in ``runtime.py`` after the existing ``builder`` template; conditional pool creation in ``startup/agent_fleet.py`` gated on ``config.swe_specialists.enabled``; tier-2 log-and-degrade on per-pool spawn failure. Five new ``_AGENT_DEPARTMENTS`` entries in ``cognitive/standing_orders.py`` mapping each specialist agent_type to ``"engineering"``. ``BuildPipeline.execute_approved_build(...)`` and the legacy ``execute_approved_build`` coroutine extended with ``specialty: str = "general"`` trailing kwarg; v1 logs the routed specialty at INFO and forwards it through; default ``"general"`` preserves today's behaviour byte-for-byte at every existing call site (build_dispatcher.py:18, routers/build.py:382 — both unchanged). **What this AD does NOT change** (out of scope by design): no production chunk auto-routing in ``execute_chunks`` (depends on AD-545/AD-546 SWE Tool Harness, GH #13 — explicit forcing function); no ModelRegistry-driven dynamic model selection (AD-463b/c MAD scoring); no Hebbian per-specialty weights (AD-476b once specialists have track records); no HXI specialty visualization (depends on AD-475c/d Ready Room work); no per-specialty standing-orders markdown (specialty-specific guidance lives in the subclass ``instructions`` attribute); no CodeReviewerAgent specialization (AD-476c if signal warrants); no new EventType; no agent identity table changes (each specialist gets its own callsign via the ``naming.py`` allocator). 14 focused tests pass at ``tests/test_ad476_specialized_builders.py`` (over the 12 floor by 2): enum 6 values + string form; ``SpecialtyMatchResult`` frozen + ``to_dict``; ``score_path`` frontend ``.tsx`` outscores backend; ``score_path`` test directory + ``test_`` prefix outscores backend ``.py``; ``score_path`` Dockerfile routes to infrastructure; ``score_path`` ``.sql`` migration routes to data; ``route_chunk`` frontend ``.tsx``; ``route_build_spec`` backend ``routers/``; ``route_build_spec`` GENERAL fallback for ``.md``; parametrized 5-specialist class-attribute matrix (specialty + agent_type + subclass-of-SWE); instructions distinct + OUTPUT FORMAT shared; config defaults + validator rejects bad tier + bad pool size; ``BuildPipeline.execute_approved_build`` signature has ``specialty="general"``; legacy ``execute_approved_build`` signature has ``specialty="general"``. Phantom-API pre-check on the prompt body: clean (the new symbols are introduced by Sections 1-7 — same intra-prompt-introduction FP class as Waves 27-49). 0 NEW phantoms. Pre-commit deletion sanity: max 0 deletions any single tracked file (additive-only changes — eight SEARCH/REPLACE blocks insert content; new modules + new test file). No hard-stops triggered: no architectural change required, no phantom in implementation, no scope creep. Closes GH issue #70.
```

**Pair 9b — `docs/development/roadmap.md:4213` flip.**

```
===MODIFY: docs/development/roadmap.md===
===SEARCH===
**AD-476: Specialized Builders — Cognitive Division of Labor for SWE** *(planned)*
===REPLACE===
**AD-476: Specialized Builders — Cognitive Division of Labor for SWE** *(v1 shipped Wave 97 — five specialist subclasses + SpecialistRouter + opt-in pools + pipeline kwarg; production chunk auto-routing + ModelRegistry per-specialty dynamic swap deferred to AD-546 + AD-463b/c respectively)*
===END REPLACE===
===END FILE===
```

**Pair 9c — `prompts/wave-plan.yaml` W97 entry append.**

Append at EOF:

```yaml

  - id: "97"
    title: "AD-476 v1 Specialized Builders — Cognitive Division of Labor for SWE"
    kind: single
    depends_on: ["96"]
    dispatch_prompt: "prompts/WAVE-97-DISPATCH.md"
    prompts_already_drafted: true
    prompt_paths:
      - "prompts/ad-476-specialized-builders-v1.md"
    builder_required: true
    issues_to_close: [70]
    notes: |
      Source-modifying v1 of AD-476 (planned at roadmap.md:4213).
      Additive specialty layer on the AD-521 SWE/Build Pipeline
      Separation that landed in Wave 96. New module
      cognitive/builder_specialist.py ships SoftwareEngineerSpecialty
      enum + SpecialtyMatchResult frozen dc + pure SpecialistRouter
      with route_build_spec + route_chunk + score_path. New module
      cognitive/builder_specialists.py ships five subclasses
      (BackendSWEAgent / FrontendSWEAgent / TestSWEAgent /
      InfrastructureSWEAgent / DataSWEAgent) each with distinct
      agent_type + specialty-tuned instructions. Five new
      _AGENT_DEPARTMENTS entries map each new agent_type to
      engineering. New SoftwareEngineerSpecialistsConfig Pydantic
      model (enabled=False default — opt-in pool spawn per AD-695
      precedent; pool_size_per_specialty=1 default;
      model_tier_overrides for the five specialty→tier mapping).
      runtime.py adds sibling import + five register_template lines
      after the existing builder template. startup/agent_fleet.py
      adds conditional pool creation block gated on
      swe_specialists.enabled. BuildPipeline.execute_approved_build
      and the legacy execute_approved_build coroutine each gain a
      specialty: str = "general" trailing kwarg; default preserves
      today's behaviour byte-for-byte at every existing call site.

      14 boundary tests at tests/test_ad476_specialized_builders.py:
      enum 6 values + string form; SpecialtyMatchResult frozen +
      to_dict; score_path frontend / test / infrastructure / data
      routing; route_chunk frontend; route_build_spec backend +
      GENERAL fallback; parametrized 5-class specialty matrix;
      instructions distinct + OUTPUT FORMAT shared; config defaults
      + validator rejection; BuildPipeline + legacy signature both
      accept specialty kwarg with default "general". Acceptance gate
      ≥+12 tests vs Captain reference baseline 12126 → ≥12138.
      Nominal +14.

      Out of scope (deferred with explicit forcing functions):
      production chunk auto-routing in execute_chunks (depends on
      AD-545/AD-546 SWE Tool Harness, GH #13); ModelRegistry MAD
      scoring + hot-swap (AD-463b/c); Hebbian per-specialty weights
      (AD-476b); HXI specialty visualization (AD-475c/d); per-specialty
      standing-orders markdown (AD-476d); CodeReviewerAgent specialization
      (AD-476c).

      No commercial leak — banned-pattern audit returns zero hits
      across all 11 patterns in this dispatch + the per-AD prompt +
      these notes. The closed-source crew-tier overlay plug-in point
      that AD-521 W96 documented (decisions-era-4-evolution.md:1453-1456)
      is preserved — each specialist class is subclassable and the
      AD-452 class-extension mechanism applies; v1 itself ships zero
      closed-source content.

      4 architect review passes:
      P1 (verify-first against HEAD 6246b35 — 12 grep-anchored
      claims confirmed: AD-476 roadmap entry at :4213, conceptual
      header at :1619, SoftwareEngineerAgent class at builder.py:1690,
      BuilderAgent alias at builder.py:2529, code_reviewer department
      mapping at standing_orders.py:43, builder template registration
      at runtime.py:706, BuilderAgent import at runtime.py:56,
      BuildPipeline signature at build_pipeline.py:56, ModelRegistry
      class at model_registry.py:83, REL_BUILDER_VARIANT at
      mesh/routing.py:31, _should_use_visiting_builder at
      builder.py:1251, CodeReviewAgent at code_reviewer.py:1; W96
      tracker omission caught — git show --name-only on a0e9bc0 +
      6246b35 confirms PROGRESS.md / DECISIONS / roadmap / wave-plan
      were NOT touched by Wave 96, decision: W97 stays AD-476-scoped
      and does NOT retroactively patch).
      P2 (reframe table — build v1 not defer; AD-546 forcing function
      well-defined; surface area bounded to two new modules + five
      subclasses + one router + one config + one runtime block; test
      impact 14 new + zero existing-test churn verified by alias
      preservation).
      P3 (banned-pattern audit on dispatch + per-AD prompt + this
      notes block — eleven patterns, zero literal-form hits;
      descriptor-only references throughout for "the e-word + tier
      phrase" and "the private commercial-repo path token" forms).
      P4 (test-plan concreteness — 14 tests named with explicit
      expected behaviours, every test's assertion grounded in a
      Section 1-7 implementation detail; signature tests (#13/#14)
      use inspect.signature so they fail loud if Section 7 not
      applied; class-attribute matrix uses pytest.parametrize for
      one-shot fan-out).

      Builder execution: read prompt top-to-bottom, apply 8
      SEARCH/REPLACE pairs across 6 MODIFY blocks (standing_orders.py,
      config.py × 2, runtime.py × 2, agent_fleet.py, build_pipeline.py
      × 2, builder.py legacy execute_approved_build) plus the 2 new
      file creates (builder_specialist.py + builder_specialists.py)
      plus the 1 new test file plus the 3 tracker updates (PROGRESS.md
      INSERT, roadmap.md flip, wave-plan.yaml append). Verify
      git diff --stat shows 6 modified source files + 3 modified
      tracker files + 3 new files plus this prompt + dispatch (which
      Builder will archive after commit). Pre-commit hook runs
      naturally on commit. Full pytest gate (expected ≥12138 passed;
      minimum gate is +12). Commit with "AD-476 v1: Specialized
      Builders — five specialist SWE subclasses + SpecialistRouter
      + opt-in pools + pipeline kwarg (+14 tests)". Archive both
      prompts. gh issue close 70 with the canonical paragraph in
      Section 8 of this per-AD prompt.
```

---

## Acceptance criteria

1. All 14 tests in `tests/test_ad476_specialized_builders.py` pass under serial run.
2. Full pytest gate: ≥12138 passed (Δ ≥ +12 vs Captain reference baseline 12126).
3. `git diff --stat` shows exactly: 6 modified source files (`config.py`, `runtime.py`, `cognitive/standing_orders.py`, `cognitive/builder.py`, `build_pipeline.py`, `startup/agent_fleet.py`) + 3 modified tracker files (`PROGRESS.md`, `docs/development/roadmap.md`, `prompts/wave-plan.yaml`) + 3 new files (`cognitive/builder_specialist.py`, `cognitive/builder_specialists.py`, `tests/test_ad476_specialized_builders.py`) + 2 archived prompts (`prompts/archive/WAVE-97-DISPATCH.md`, `prompts/archive/ad-476-specialized-builders-v1.md`).
4. `gh issue view 70 --json state` returns `"CLOSED"` after the close step.
5. Pre-commit hook passes naturally on commit (no `--no-verify` shortcuts).
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-07, HEAD 6246b35)

```
findstr /N /C:"AD-476" docs\development\roadmap.md
  1619:    *Specialized Builders (Cognitive Division of Labor for SWE):* *(AD-476)*
  4213:    **AD-476: Specialized Builders — Cognitive Division of Labor for SWE** *(planned)*

findstr /N /C:"class SoftwareEngineerAgent" /C:"BuilderAgent = SoftwareEngineerAgent" src\probos\cognitive\builder.py
  1690: class SoftwareEngineerAgent(CognitiveAgent):
  2529: BuilderAgent = SoftwareEngineerAgent

findstr /N /C:"\"builder\": \"engineering\"" /C:"\"code_reviewer\": \"engineering\"" src\probos\cognitive\standing_orders.py
  42:    "builder": "engineering",
  43:    "code_reviewer": "engineering",

findstr /N /C:"register_template(\"builder\"" /C:"from probos.cognitive.builder import BuilderAgent" src\probos\runtime.py
  56:  from probos.cognitive.builder import BuilderAgent
  706:  self.spawner.register_template("builder", BuilderAgent)

findstr /N /C:"async def execute_approved_build" src\probos\build_pipeline.py
  56:  async def execute_approved_build(

findstr /N /C:"async def execute_approved_build" src\probos\cognitive\builder.py
  2532: async def execute_approved_build(

findstr /N /C:"class ChunkSpec" /C:"class BuildSpec" src\probos\cognitive\builder.py
  324:  class ChunkSpec:
  (BuildSpec confirmed by separate read at the existing dataclass region above ChunkSpec)

findstr /N /C:"class ModelRegistry:" src\probos\cognitive\model_registry.py
  83:   class ModelRegistry:

findstr /N /C:"REL_BUILDER_VARIANT" src\probos\mesh\routing.py
  31:   REL_BUILDER_VARIANT = "builder_variant"  # build_code → native|visiting (AD-353)

findstr /N /C:"def _should_use_visiting_builder" src\probos\cognitive\builder.py
  1251: def _should_use_visiting_builder(

findstr /N /C:"class CodeReviewAgent" src\probos\cognitive\code_reviewer.py
  (file header at line 1 confirms; class declaration follows — verified by read)

git show --name-only a0e9bc0 6246b35
  (W96 commits — confirmed PROGRESS.md / DECISIONS / roadmap / wave-plan UNTOUCHED;
   only build_pipeline.py + cognitive/builder.py + runtime.py + test_ad521 + the
   two archived prompts were modified)

gh issue view 70 --json number,title,state
  {"number":70,"state":"OPEN","title":"AD-476: Specialized Builders — Cognitive Division of Labor for SWE"}

.venv\Scripts\pytest.exe tests/ -q -n 4 --dist=loadfile (live at HEAD 6246b35)
  6 failed, 12120 passed, 16 skipped, 125 warnings in 548.53s (0:09:08)

.venv\Scripts\pytest.exe --collect-only -q tests/
  12142 tests collected in 5.80s
```
