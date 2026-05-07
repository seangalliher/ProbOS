"""Five SoftwareEngineerAgent specialist subclasses (AD-476).

Each subclass overrides:
- ``agent_type`` — distinct from base ``"builder"`` for crew-roster identity
  (per AD-398 crew identity continuity rules; the base ``builder`` agent_type
  is unchanged).
- ``specialty`` — the SoftwareEngineerSpecialty enum value this class handles.
- ``instructions`` — specialty-tuned overlay of the base SWE instructions.

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
