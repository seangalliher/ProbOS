# AD-596a: Cognitive Skill File Format + Loader

**Priority:** High — Foundation for T2 cognitive skills (AD-596b-e depend on this)
**Issue:** #166
**Scope:** OSS (`d:\ProbOS`)
**Dependencies:** None (first in chain)
**Connects to:** AD-596b (intent integration), AD-428 (Skill Framework bridge via AD-596c), AD-625 (Communication Discipline — first T2 cognitive skill)

---

## Context

ProbOS has four capability tiers:

| Tier | What | Status |
|------|------|--------|
| T1: Standing Orders | Role identity + behavioral standards | **Built** (AD-339) |
| T2: Cognitive Skills | Task-specific instruction-defined capabilities | **This AD** |
| T3: Executable Skills | Deterministic procedures from Cognitive JIT | **Built** (AD-531-539) |
| T4: Tool Skills | Code/tool execution wrappers | **Built** (AD-423) |

T2 is the gap. Currently, task-specific capabilities are embedded in standing orders (conflating "who you are" with "what you can do") or hardcoded in Python (`_handled_intents` sets). This AD adopts the [AgentSkills.io](https://agentskills.io) open standard (`SKILL.md` format) to define cognitive skills as composable, discoverable, independently versionable files.

**Problem this solves:** Standing orders load fully into every cognitive cycle. There is no mechanism to load skill instructions on-demand. This wastes context budget on capabilities irrelevant to the current task. BF-146 demonstrated that conflating identity and capabilities in standing orders causes confabulation.

**Design principle:** Progressive disclosure. At startup, only skill names + descriptions (~100 tokens each) are loaded. Full instructions (<5000 tokens) are loaded on-demand when an intent matches.

---

## What to Build

### 1. Skill File Format

Create the `config/skills/` directory structure. Each skill is a directory containing a `SKILL.md` file following the AgentSkills.io standard:

```
config/skills/
  architecture-review/
    SKILL.md
  trust-analysis/
    SKILL.md
```

`SKILL.md` uses YAML frontmatter (standard AgentSkills.io fields) with optional ProbOS metadata extensions:

```yaml
---
name: architecture-review
description: >
  Analyze proposed system designs against ProbOS architectural principles.
  Use when reviewing design proposals, enhancement requests, or refactoring plans.
license: Apache-2.0
compatibility: Requires CodebaseIndex access
metadata:
  probos-department: science
  probos-skill-id: architecture_review
  probos-min-proficiency: 3
  probos-min-rank: lieutenant
  probos-intents: "design_feature review_architecture"
---

# Architecture Review
## When to use
...instructions...
```

**Standard AgentSkills.io fields** (required/optional per spec):
- `name` (required): Skill identifier, lowercase with hyphens
- `description` (required): When to use this skill (~100 tokens max for progressive disclosure)
- `license` (optional): SPDX identifier
- `compatibility` (optional): Requirements for the skill to work
- `metadata` (optional): Extension point — ProbOS uses this for governance

**ProbOS metadata extensions** (all optional — external skills work without them):
- `probos-department`: Scopes which agents can discover the skill. Must match a department in ontology. `"*"` or omitted = available to all.
- `probos-skill-id`: Links to `SkillDefinition` in `SkillRegistry` (AD-428) for proficiency tracking. If present, must match an existing `skill_id` in the registry.
- `probos-min-proficiency`: Minimum `ProficiencyLevel` value (1-7) required to activate. Default: 1 (FOLLOW).
- `probos-min-rank`: Minimum `Rank` value (`ensign`, `lieutenant`, `commander`, `senior_officer`). Default: `ensign`.
- `probos-intents`: Space-separated intent names this skill handles. Replaces hardcoded `_handled_intents` (AD-596b will wire this).

### 2. `CognitiveSkillCatalog` Class

**File:** `src/probos/cognitive/skill_catalog.py` (new file)

This is the core class — a Ship's Computer infrastructure service (no identity, no crew status).

```python
@dataclass
class CognitiveSkillEntry:
    """Metadata for a discovered cognitive skill."""
    name: str                          # From SKILL.md frontmatter
    description: str                   # From SKILL.md frontmatter
    skill_dir: Path                    # Directory containing SKILL.md
    license: str                       # From frontmatter, default ""
    compatibility: str                 # From frontmatter, default ""
    # ProbOS governance (from metadata block, all optional)
    department: str                    # Default "*" (all departments)
    skill_id: str                      # Default "" (no proficiency tracking)
    min_proficiency: int               # Default 1 (FOLLOW)
    min_rank: str                      # Default "ensign"
    intents: list[str]                 # Default [] (no intent routing)
    origin: str                        # "internal" or "external"
    loaded_at: float                   # time.time() when discovered
```

```python
class CognitiveSkillCatalog:
    """Ship's Computer service — discovers, indexes, and serves cognitive skill files.

    Infrastructure tier (no identity). Provides progressive disclosure:
    descriptions at startup, full instructions on-demand.
    """

    def __init__(
        self,
        skills_dir: Path | None = None,
        db_path: str | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        ...
```

**Public methods:**

- `async start() -> None` — Initialize SQLite table, scan `skills_dir`, register all discovered skills.
- `async stop() -> None` — Close DB connection.
- `async scan_and_register() -> int` — Scan `config/skills/` for `SKILL.md` files, parse frontmatter, register each. Return count of skills registered. Idempotent — re-scanning updates existing entries.
- `register(entry: CognitiveSkillEntry) -> None` — Add/update a skill in the catalog (in-memory cache + SQLite).
- `get_entry(name: str) -> CognitiveSkillEntry | None` — Lookup by name.
- `list_entries(department: str | None = None, min_rank: str | None = None) -> list[CognitiveSkillEntry]` — List skills, optionally filtered by department and rank.
- `get_descriptions(department: str | None = None, agent_rank: str | None = None) -> list[tuple[str, str]]` — Return `[(name, description), ...]` for progressive disclosure. Only skills the agent is allowed to see (department + rank filtering).
- `get_instructions(name: str) -> str | None` — Load and return full SKILL.md content (below the frontmatter). This is the on-demand loading for activation. Returns `None` if skill not found.
- `get_intents(name: str) -> list[str]` — Return declared intents for a skill.
- `find_by_intent(intent_name: str) -> list[CognitiveSkillEntry]` — Reverse lookup: which skills handle a given intent?

**SQLite schema** (catalog metadata only — instructions stay in files):

```sql
CREATE TABLE IF NOT EXISTS cognitive_skill_catalog (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    skill_dir TEXT NOT NULL,
    license TEXT DEFAULT '',
    compatibility TEXT DEFAULT '',
    department TEXT DEFAULT '*',
    skill_id TEXT DEFAULT '',
    min_proficiency INTEGER DEFAULT 1,
    min_rank TEXT DEFAULT 'ensign',
    intents TEXT DEFAULT '[]',   -- JSON array
    origin TEXT DEFAULT 'internal',
    loaded_at REAL NOT NULL
);
```

### 3. `SkillFileLoader` — Frontmatter Parser

**File:** Same file (`src/probos/cognitive/skill_catalog.py`) or a utility function within it.

Parses `SKILL.md` files:
1. Read file content
2. Extract YAML frontmatter (between `---` delimiters)
3. Parse YAML into dict
4. Extract standard fields (`name`, `description`, `license`, `compatibility`)
5. Extract ProbOS metadata from `metadata` dict (with defaults for missing fields)
6. Return `CognitiveSkillEntry`

Use `yaml.safe_load()` for parsing. Do NOT add `pyyaml` as a new dependency — it's already in `pyproject.toml` requirements.

**Error handling:**
- Missing `---` delimiters → log warning, skip file
- Missing required `name` field → log warning, skip file
- Missing required `description` field → log warning, skip file
- Invalid YAML → log warning, skip file
- Missing `metadata` block → use defaults (ungoverned skill)
- Missing individual metadata fields → use field-specific defaults

### 4. REST API Endpoints

**File:** `src/probos/routers/skills.py` (EXISTING file — add new endpoints alongside existing AD-428 endpoints)

New endpoints under the existing `/api/skills/` router:

- `GET /api/skills/catalog` — List all cognitive skills (name + description + metadata). Query params: `department`, `rank` for filtering.
- `GET /api/skills/catalog/{name}` — Get full skill entry including instructions content.
- `POST /api/skills/catalog/rescan` — Trigger `scan_and_register()` to pick up new/changed skill files.

### 5. Startup Wiring

**File:** `src/probos/startup/communication.py`

Wire `CognitiveSkillCatalog` into the startup sequence. Follow the existing pattern for `SkillRegistry`/`AgentSkillService` (lines 279-287):

```python
# After SkillRegistry/AgentSkillService setup (insert at line 288, after logger.info):
from probos.cognitive.skill_catalog import CognitiveSkillCatalog

# Derive config/skills/ path the same way ontology_dir is derived (see line 302 pattern)
skills_dir = Path(__file__).resolve().parent.parent.parent.parent / "config" / "skills"
cognitive_catalog = CognitiveSkillCatalog(
    skills_dir=skills_dir,
    db_path=str(data_dir / "cognitive_skills.db"),
)
await cognitive_catalog.start()
```

Note: `config_dir` does NOT exist as a variable in this file. Derive the path using the `Path(__file__)` traversal pattern already used at line 302 for `ontology_dir`. No `connection_factory` is passed — follow the same pattern as `SkillRegistry(db_path=skills_db)` at line 282 which defaults internally.

Add `cognitive_skill_catalog` to the `CommunicationResult` dataclass in `startup/results.py` (note: singular `Result`, not `Results`). Add as `"CognitiveSkillCatalog | None"` type — follow the nullable pattern used by most other fields.

Wire shutdown in `startup/shutdown.py` — call `await cognitive_catalog.stop()`.

Store reference on runtime: `runtime.cognitive_skill_catalog = cognitive_catalog`.

### 6. Create Example Skill (Placeholder)

Create `config/skills/communication-discipline/SKILL.md` as a minimal placeholder to validate the loader works. This will be fully developed in AD-625.

```yaml
---
name: communication-discipline
description: >
  Evaluate whether a Ward Room reply adds new information before posting.
  Use before composing any reply to a shared channel or thread.
license: Apache-2.0
metadata:
  probos-department: "*"
  probos-skill-id: ward_room_discipline
  probos-min-proficiency: 1
  probos-min-rank: ensign
  probos-intents: "proactive_think"
---

# Communication Discipline

## When to Use
Before posting any reply to a Ward Room channel or thread.

## Instructions
*Placeholder — full instructions will be developed in AD-625.*

1. Read the entire thread before composing a reply.
2. Ask: "What new information does my reply add?"
3. If your reply is primarily agreement or confirmation, use [ENDORSE] instead.
```

---

## Engineering Principles Compliance

- **Single Responsibility:** `CognitiveSkillCatalog` does one thing — file discovery, parsing, and serving. No intent routing (AD-596b), no proficiency tracking (AD-596c), no validation (AD-596e).
- **Open/Closed:** Catalog is extensible via `register()` without modifying the class. ProbOS metadata is additive — external skills work without it.
- **Dependency Inversion:** Constructor injection for `connection_factory`. No direct `aiosqlite.connect()`.
- **Cloud-Ready Storage:** Uses abstract `ConnectionFactory` pattern per existing convention (see `SkillRegistry.__init__` at `skill_framework.py:323`).
- **Interface Segregation:** `CognitiveSkillCatalog` exposes narrow public API. Consumers depend on specific methods, not the whole class.
- **Law of Demeter:** No reaching through objects. Catalog is accessed directly, not via `runtime.skill_registry.catalog`.
- **Fail Fast:** Invalid skill files are logged and skipped (log-and-degrade). Missing `config/skills/` directory is not an error — catalog starts empty.
- **DRY:** Reuse `ConnectionFactory` from existing storage pattern. Reuse `yaml.safe_load()` — no custom parser.
- **Defense in Depth:** Validate frontmatter at parse time. Department/rank values validated against known enums where possible (advisory warnings, not hard failures — external skills may use unknown values).

---

## Test Requirements

**File:** `tests/test_cognitive_skill_catalog.py` (new)

Minimum test coverage:

**SkillFileLoader / Parsing:**
- `test_parse_valid_skill_md` — Full frontmatter with all ProbOS metadata
- `test_parse_minimal_skill_md` — Only required fields (name, description), no metadata
- `test_parse_external_skill_no_probos_metadata` — Standard AgentSkills.io with no `metadata` block
- `test_parse_missing_name_skips` — Missing `name` → skip with warning
- `test_parse_missing_description_skips` — Missing `description` → skip with warning
- `test_parse_invalid_yaml_skips` — Malformed YAML → skip with warning
- `test_parse_no_frontmatter_skips` — No `---` delimiters → skip with warning
- `test_parse_preserves_body_content` — Content below frontmatter preserved for `get_instructions()`

**CognitiveSkillCatalog:**
- `test_start_creates_table` — SQLite schema created on start
- `test_scan_discovers_skills` — Scan finds `SKILL.md` files in subdirectories
- `test_scan_ignores_non_skill_dirs` — Directories without `SKILL.md` are skipped
- `test_scan_idempotent` — Re-scanning updates, doesn't duplicate
- `test_register_and_get_entry` — Round-trip register → get
- `test_list_entries_no_filter` — Returns all entries
- `test_list_entries_department_filter` — Only matching department + wildcard skills
- `test_list_entries_rank_filter` — Only skills at or below the given rank
- `test_get_descriptions_progressive_disclosure` — Returns (name, description) tuples only
- `test_get_instructions_loads_body` — Full markdown body returned (no frontmatter)
- `test_get_instructions_missing_skill` — Returns None
- `test_get_intents` — Returns parsed intent list
- `test_find_by_intent` — Reverse lookup by intent name
- `test_find_by_intent_no_match` — Returns empty list

**REST API:**
- `test_api_catalog_list` — GET /api/skills/catalog returns entries
- `test_api_catalog_get` — GET /api/skills/catalog/{name} returns full entry + instructions
- `test_api_catalog_rescan` — POST /api/skills/catalog/rescan triggers scan

**Integration:**
- `test_startup_wiring` — Catalog created and started during communication startup
- `test_shutdown_cleanup` — Catalog stopped during shutdown

---

## Files to Create

| File | Purpose |
|------|---------|
| `src/probos/cognitive/skill_catalog.py` | `CognitiveSkillCatalog`, `CognitiveSkillEntry`, loader functions |
| `config/skills/communication-discipline/SKILL.md` | Placeholder skill for loader validation |
| `tests/test_cognitive_skill_catalog.py` | All tests |

## Files to Modify

| File | Change |
|------|--------|
| `src/probos/startup/communication.py` | Wire `CognitiveSkillCatalog` startup after SkillRegistry (line ~286) |
| `src/probos/startup/results.py` | Add `cognitive_skill_catalog` to `CommunicationResults` dataclass |
| `src/probos/startup/shutdown.py` | Add catalog shutdown (after skill_service shutdown, line ~228) |
| `src/probos/routers/skills.py` | Add `/api/skills/catalog` endpoints |
| `src/probos/runtime.py` | Add `self.cognitive_skill_catalog: CognitiveSkillCatalog | None = None` attribute (class-level annotation near line 210, `__init__` near line 430, assignment from `comm.cognitive_skill_catalog` near line 1396 — follow the `skill_registry` pattern exactly) |

## Files NOT to Modify

- `proactive.py` — Intent integration is AD-596b
- `standing_orders.py` — compose_instructions() integration is AD-596b
- `skill_framework.py` — Registry bridge is AD-596c
- `agent_onboarding.py` — Onboarding integration is AD-596b

---

## Verification

After implementation:
1. `pytest tests/test_cognitive_skill_catalog.py -v` — All tests pass
2. `pytest tests/test_skill_framework.py -v` — Existing skill tests unbroken
3. `pytest tests/ -x --timeout=60` — Full suite passes (run in background)
4. Start runtime → verify `config/skills/communication-discipline/SKILL.md` is discovered → check `/api/skills/catalog` returns it
