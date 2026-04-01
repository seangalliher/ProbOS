# BF-095: God Object Reduction — VesselOntologyService and WardRoomService

## Context

Wave 3 decomposed the three largest god objects: `runtime.py` (5,321→2,762, −48%), `api.py` (3,109→295, −91%), `shell.py` (1,883→507, −73%). Five classes with 39+ methods remain. Shell (69) and Runtime (61) are hard to decompose further without architectural change. **VesselOntologyService (54 methods, 1,060 lines)** and **WardRoomService (39 methods, 1,612 lines)** are tractable using the same extraction pattern.

This is the largest scope item in Wave 6. Follow the Wave 3 pattern exactly:
- Extract sub-service **classes** (not functions) into sub-modules
- Parent class becomes a thin **facade** that instantiates sub-services and delegates
- `__init__.py` files are minimal (single docstring, no re-exports)
- Dependencies passed explicitly via constructor injection

## Part 1: VesselOntologyService Decomposition

File: `src/probos/ontology.py` (1,060 lines, class starts at line 278)

### 1a. New package structure

```
src/probos/ontology/
    __init__.py           # Docstring only
    service.py            # VesselOntologyService facade (thin, ≤20 methods)
    loader.py             # OntologyLoader (YAML I/O)
    departments.py        # DepartmentService (org structure, assignments)
    ranks.py              # RankService (promotions, qualifications)
    models.py             # All dataclasses currently in ontology.py lines 1-276
```

### 1b. Move data models → `models.py`

Lines 1-276 of `ontology.py` contain dataclasses (`VesselIdentity`, `Department`, `Post`, `Assignment`, `AlertCondition`, `RoleTemplate`, `QualificationPath`, etc.). Move them all to `ontology/models.py`.

### 1c. Extract `OntologyLoader` → `loader.py`

**11 methods** — all YAML I/O and initialization:

| Method | Description |
|--------|-------------|
| `initialize()` | Top-level async loader, calls all `_load_*` methods |
| `_load_vessel()` | Loads vessel.yaml |
| `_load_or_generate_instance_id()` | Instance UUID persistence |
| `_load_or_generate_instance_id_sync()` | Sync helper for instance ID (from BF-094) |
| `_load_organization()` | Loads organization.yaml |
| `_load_skills_schema()` | Loads skills.yaml |
| `_load_operations_schema()` | Loads operations.yaml |
| `_load_communication_schema()` | Loads communication.yaml |
| `_load_resources_schema()` | Loads resources.yaml |
| `_load_records_schema()` | Loads records.yaml |
| `_read_yaml_sync()` | Shared sync helper (new from BF-094) |

**Constructor:** Takes `schema_dir: Path`. After loading, exposes loaded data as public attributes that the facade reads.

```python
class OntologyLoader:
    """Loads vessel ontology YAML schemas into structured data."""

    def __init__(self, schema_dir: Path):
        self.schema_dir = schema_dir
        # All the dict/list attributes that _load_* methods populate
        self.vessel_identity: VesselIdentity | None = None
        self.departments: dict[str, Department] = {}
        self.posts: dict[str, Post] = {}
        self.assignments: dict[str, Assignment] = {}
        # ... etc.

    async def initialize(self) -> None:
        """Load all ontology schemas from YAML."""
        # Existing initialize() logic
```

### 1d. Extract `DepartmentService` → `departments.py`

**14 methods** — org structure queries and agent wiring:

| Method | Description |
|--------|-------------|
| `get_departments()` | Return all departments |
| `get_department()` | Return department by ID |
| `get_posts()` | Return posts, filtered by department |
| `get_post()` | Return post by ID |
| `get_chain_of_command()` | Walk reports_to chain |
| `get_direct_reports()` | Posts reporting to a post |
| `get_assignment_for_agent()` | Assignment by agent_type |
| `get_agent_department()` | Department for an agent_type |
| `get_crew_agent_types()` | Set of crew-tier agent types |
| `get_post_for_agent()` | Post for an agent_type |
| `wire_agent()` | Associate runtime agent_id with post |
| `update_assignment_callsign()` | Update callsign on assignment |
| `get_assignment_for_agent_by_id()` | Find assignment by runtime agent_id |
| `get_crew_context()` | Assemble crew context dict (134 lines) |

**Constructor:** Takes references to `departments`, `posts`, `assignments` dicts (shared with loader output).

### 1e. Extract `RankService` → `ranks.py`

**5 methods** — promotion and qualification queries:

| Method | Description |
|--------|-------------|
| `get_role_template()` | Skill requirements for a post |
| `get_role_template_for_agent()` | Role template for agent's post |
| `get_qualification_path()` | Qualification path for rank transition |
| `get_all_qualification_paths()` | All defined paths |
| `set_skill_service()` | Inject AgentSkillService reference |

**Constructor:** Takes references to `role_templates`, `qualification_paths` dicts, and `assignments`.

### 1f. Facade → `service.py`

`VesselOntologyService` becomes a thin facade that:
1. Instantiates `OntologyLoader`, `DepartmentService`, `RankService` in `__init__`
2. Delegates `initialize()` to loader, then passes loaded data to sub-services
3. Retains the 24 trivial getter methods (vessel state, operations, communication, resources, records queries) directly — they are one-liner returns on loaded data, not worth extracting
4. Delegates department/rank methods to sub-services

**Target: ≤20 direct methods.** The 24 getters are tiny (1-2 lines each), so the facade stays lean even with them.

### 1g. Update imports

Every file that imports from `probos.ontology` needs updating. Key consumers:
- `from probos.ontology import VesselOntologyService` → `from probos.ontology.service import VesselOntologyService`
- OR add re-export in `__init__.py`: `from probos.ontology.service import VesselOntologyService`

**Recommendation:** Re-export `VesselOntologyService` and the data models from `ontology/__init__.py` for backward compatibility:

```python
"""VesselOntologyService — vessel structure, organization, and schema management."""
from probos.ontology.models import (
    VesselIdentity, Department, Post, Assignment, AlertCondition,
    RoleTemplate, QualificationPath,
    # ... all other dataclasses
)
from probos.ontology.service import VesselOntologyService

__all__ = ["VesselOntologyService", ...]
```

This way existing `from probos.ontology import VesselOntologyService` continues to work.

## Part 2: WardRoomService Decomposition

File: `src/probos/ward_room.py` (1,612 lines, class starts at line 216)

### 2a. New package structure

```
src/probos/ward_room/
    __init__.py           # Re-exports WardRoomService + models
    service.py            # WardRoomService facade (thin)
    channels.py           # ChannelManager (channel CRUD)
    threads.py            # ThreadManager (thread lifecycle, pruning)
    messages.py           # MessageStore (posts, endorsements, credibility)
    models.py             # All dataclasses/schemas from ward_room.py lines 1-215
```

### 2b. Move data models → `models.py`

Lines 1-215 contain the `Channel`, `Thread`, `Post`, `Endorsement`, etc. dataclasses. Move them all to `ward_room/models.py`.

### 2c. Extract `ChannelManager` → `channels.py`

**7 methods:**

| Method | Description |
|--------|-------------|
| `_ensure_default_channels()` | Create startup channels |
| `list_channels()` | Return all channels |
| `create_channel()` | Create custom channel with credibility check |
| `get_channel()` | Return channel by ID |
| `get_or_create_dm_channel()` | Deterministic DM channel |
| `_refresh_channel_cache()` | Rebuild channel cache |
| `get_channel_snapshot()` | Cached channels for state_snapshot |

**Constructor:** Takes `db` connection, `credibility_threshold: float`, optional `ontology` reference.

### 2d. Extract `ThreadManager` → `threads.py`

**12 methods:**

| Method | Description |
|--------|-------------|
| `list_threads()` | List threads with sort/pagination |
| `browse_threads()` | Cross-channel thread browsing |
| `get_recent_activity()` | Recent threads + posts since timestamp |
| `create_thread()` | Create thread (with episodic memory + event emission) |
| `update_thread()` | Update thread fields |
| `get_thread()` | Thread with nested post tree |
| `archive_dm_messages()` | Archive old DM posts |
| `prune_old_threads()` | Prune with JSONL archival (BF-094 async version) |
| `count_pruneable()` | Dry-run prune count |
| `start_prune_loop()` | Start background pruning |
| `_prune_loop()` | Periodic pruning inner loop |
| `stop_prune_loop()` | Cancel prune task |

**Constructor:** Takes `db` connection, `archive_dir: str | None`, optional `episodic_memory` and `hebbian` references. Inherits `EventEmitterMixin` (or receives an emitter callback).

**Design note on `create_thread()`:** This method records episodic memory and emits events. The ThreadManager either needs references to episodic_memory/hebbian (passed via constructor), or the facade wraps the call and adds episodic/event side-effects. **Prefer:** Pass references to ThreadManager — keeps side-effects co-located with the operation, avoids the facade growing logic.

### 2e. Extract `MessageStore` → `messages.py`

**10 methods** (posts + endorsements + membership + credibility):

| Method | Description |
|--------|-------------|
| `create_post()` | Reply to thread (with episodic memory + Hebbian) |
| `get_post()` | Return post by ID |
| `edit_post()` | Edit own post |
| `endorse()` | Up/down/unvote |
| `get_credibility()` | Credibility record for agent |
| `_update_credibility()` | Recalculate credibility |
| `subscribe()` | Subscribe agent to channel |
| `unsubscribe()` | Remove membership |
| `update_last_seen()` | Mark all as read |
| `get_unread_counts()` | Unread thread counts |

**Constructor:** Takes `db` connection, optional `episodic_memory`, `hebbian`, `trust_network` references.

### 2f. Facade → `service.py`

`WardRoomService` becomes a thin facade:
1. Owns the `db` connection (opens/closes in `start()`/`stop()`)
2. Instantiates `ChannelManager`, `ThreadManager`, `MessageStore` in `start()` (after DB is opened)
3. Delegates all operations to sub-services
4. Retains: `__init__`, `start`, `stop`, `get_stats`, `_extract_mentions`, `get_unread_dms`, `is_started` — the lifecycle/utility methods (~7 methods)

**Dead code removal:** `post_system_message()` and `set_ontology()` have **zero production callers** (confirmed by grep). Delete them entirely — do not move to sub-services. If any test directly calls them, update the test to remove the dead-code coverage.

**DB sharing:** All sub-services receive the same `aiosqlite` connection object. The facade owns the connection lifecycle.

### 2g. Fix Law of Demeter violations

Three external files reach directly into `WardRoomService._db` to run raw SQL:

| File | Access pattern | Fix |
|------|---------------|-----|
| `src/probos/assignment.py` | `ward_room._db.execute(...)` to query channel membership | Add a public method on `ChannelManager` (e.g., `get_channel_members(channel_id)`) and call through the facade |
| `src/probos/startup/finalize.py` | `ward_room._db.execute(...)` for startup channel verification | Use public `list_channels()` or add a verification method |
| `src/probos/startup/shutdown.py` | `ward_room._db` access during shutdown | Use public API or move logic into `WardRoomService.stop()` |

**Rule:** After this refactor, no file outside `src/probos/ward_room/` should access `_db`. Any remaining `ward_room._db` references are violations.

### 2h. Update imports

Same pattern as ontology — re-export from `__init__.py`:

```python
"""Ward Room — Agent Communication Fabric."""
from probos.ward_room.models import Channel, Thread, Post, Endorsement
from probos.ward_room.service import WardRoomService

__all__ = ["WardRoomService", "Channel", "Thread", "Post", "Endorsement"]
```

## Part 3: Tests

### 3a. Existing tests must still pass

All existing tests for ontology and ward_room should pass without modification. The facade preserves the exact same public API.

### 3b. New sub-service unit tests

Optional but recommended — add tests for sub-services in isolation:
- `test_ontology_loader.py` — test YAML loading with fixture files
- `test_department_service.py` — test department queries with mock data
- `test_channel_manager.py` — test channel CRUD with in-memory DB
- `test_thread_manager.py` — test thread lifecycle with in-memory DB

### 3c. Import compatibility test

Add a test that verifies backward-compatible imports still work:
```python
def test_ontology_import_compat():
    from probos.ontology import VesselOntologyService, Department, Post
    assert VesselOntologyService is not None

def test_ward_room_import_compat():
    from probos.ward_room import WardRoomService, Channel, Thread, Post
    assert WardRoomService is not None
```

## Verification

```bash
# Full test suite — this is a structural refactor, run everything
uv run pytest tests/ -v

# Verify method counts
python -c "
import ast, sys
for f in ['src/probos/ontology/service.py', 'src/probos/ward_room/service.py']:
    tree = ast.parse(open(f).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            print(f'{f}: {node.name} has {len(methods)} methods')
"
```

Target: Both facades ≤20 methods.

```bash
# Verify no Law of Demeter violations remain
grep -rn "ward_room\._db" src/probos/ --include="*.py" | grep -v "ward_room/"
# Should return zero results
```

## Principles Compliance

- **SOLID (SRP):** Each sub-service has one responsibility — loading, departments, channels, threads, messages
- **SOLID (DIP):** Sub-services receive dependencies via constructor, not by reaching into a parent
- **Law of Demeter:** Facade delegates, never exposes sub-service internals
- **DRY:** Ontology's 7 identical YAML load patterns share `_read_yaml_sync` (per BF-094)
- **Cloud-Ready:** DB connection sharing is clean and compatible with connection pooling (future)

## Risk Assessment

**Medium risk** — structural refactor touching two widely-used services. Mitigations:
1. Backward-compatible `__init__.py` re-exports mean no import changes needed in consumers
2. Public API is identical — facade delegates 1:1
3. Full test suite as gate
4. If time-boxed, do ontology first (simpler, fewer cross-cutting concerns), then ward_room
