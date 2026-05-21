# AD-750 - WorkIQ-Style Semantic Work Layer

Status: drafted (planning slate only)
Issue: #696
Parent: #486
Depends on: AD-749 (#695)

## Objective
Create a shared semantic work layer so Yeo and all crew agents reason over commitments, context, and artifacts consistently.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- Semantic entity model for tasks, meetings, docs, threads, commitments.
- Query/retrieval APIs for delegation and daily planning flows.
- Session continuity model (AionUi session-manager pattern, architecture only).
- Mapping from existing task/journal data to new semantic layer.

## Out of Scope
- Commercial analytics/scoring/reporting overlays.
- Replacing episodic memory primitives wholesale.

## OSS vs Commercial Split

**OSS (Personal Desktop):**
- Semantic entity model for personal tasks, meetings, docs, commitments.
- Query/retrieval for personal daily planning and delegation.
- Session continuity for active assistant sessions.

**Commercial Extension Point:**
- Org-wide entity indexing and cross-user query surfaces.
- Team/org-level commitment tracking and project analytics.
- Compliance-grade retention and audit for work semantics.

## File Targets
- `src/probos/knowledge/`
- `src/probos/ontology/`
- `src/probos/cognitive/`
- `src/probos/routers/` (query APIs)
- `src/probos/types.py`

## Pre-Flight Anchors
- Verify existing semantic hooks in `src/probos/cognitive/oracle_service.py`.
- Verify ontology services in `src/probos/ontology/service.py`.
- Verify current records/query surfaces in `src/probos/routers/records.py` and `src/probos/knowledge/`.

## Implementation Spec

### Section 1: Semantic Entity Models

**File:** `src/probos/types.py` (extend existing)

Add dataclasses:
```python
@dataclass
class SemanticEntity:
    """Base for all work semantics (personal data model)."""
    id: str  # UUID
    entity_type: str  # "task" | "meeting" | "commitment" | "thread" | "document"
    owner_id: str  # Captain's local identifier
    created_at: datetime
    modified_at: datetime
    content: str  # plaintext/reference (not full doc body)

@dataclass
class Task(SemanticEntity):
    title: str
    due_date: datetime | None = None
    completed: bool = False
    delegated_to_agent: str | None = None  # "OutlookAgent", "ArchitectAgent", etc.
    priority: int = 1  # 1-5 scale

@dataclass
class Meeting(SemanticEntity):
    title: str
    start_time: datetime
    end_time: datetime
    attendees: list[str]
    location: str | None = None

@dataclass
class Commitment(SemanticEntity):
    description: str
    deadline: datetime
    stake_agent: str  # who is holding the commitment (e.g. "BuilderAgent")
    status: str  # "open" | "in_progress" | "completed" | "blocked"

@dataclass
class WorkThread(SemanticEntity):
    topic: str
    messages: list[dict]  # message objects with timestamp, author, content
    related_tasks: list[str]  # Task.ids
    related_meetings: list[str]  # Meeting.ids
```

### Section 2: Semantic Store & Query APIs

**File:** `src/probos/knowledge/semantic_store.py` (new)

Create `SemanticStore` class:
```python
class SemanticStore:
    def __init__(self, db_path: str, owner_id: str):
        """Initialize semantic store (SQLite, indexed for queries)."""
    
    async def insert_entity(self, entity: SemanticEntity) -> None:
        """Add task/meeting/commitment/thread to store."""
    
    async def query_tasks(self, due_before: datetime | None = None, completed: bool = False) -> list[Task]:
        """List incomplete tasks, optionally filtered by due date."""
    
    async def query_meetings(self, date_range: tuple[datetime, datetime]) -> list[Meeting]:
        """List meetings in date range."""
    
    async def query_commitments(self, status: str = "open") -> list[Commitment]:
        """List open commitments (what crew owes to each other)."""
    
    async def search(self, query: str) -> list[SemanticEntity]:
        """Full-text search across all entities (ChromaDB semantic + SQLite keyword)."""
    
    async def link_entities(self, source_id: str, target_ids: list[str], link_type: str) -> None:
        """Create cross-references (task depends on meeting, etc.)."""
```

**Tests:** `tests/test_semantic_store.py` (3 tests)
- Insert + query: task creation and retrieval
- Cross-linking: query by related entities
- Search: full-text finds tasks by content

### Section 3: Session Continuity Model (AionUi Pattern)

**File:** `src/probos/cognitive/session_manager.py` (new)

Create `Session` dataclass + `SessionManager`:
```python
@dataclass
class Session:
    id: str  # UUID
    platform: str  # "desktop" | "web" | etc.
    user_id: str  # Captain identifier
    agent_type: str  # "Yeo" | "ArchitectAgent", etc.
    started_at: datetime
    last_activity: datetime
    active_tasks: list[str]  # Task.ids for this session
    context: dict  # working memory snapshot

class SessionManager:
    async def create_session(self, agent_type: str) -> Session:
        """Start new session, store to disk."""
    
    async def restore_session(self, session_id: str) -> Session | None:
        """Load session from disk (graceful degradation if not found)."""
    
    async def update_session_context(self, session_id: str, context: dict) -> None:
        """Save working memory for session recovery on restart."""
    
    async def close_session(self, session_id: str) -> None:
        """Mark session complete, archive to history."""
```

**Storage:** Local JSON files in `data/sessions/`, NOT cloud (OSS scope).

**Tests:** `tests/test_session_manager.py` (2 tests)
- Create + restore: session survives restart
- Context persistence: working memory saved/loaded

### Section 4: Mapping from Existing Data

**File:** `src/probos/integrations/semantic_mapper.py` (new)

Create `SemanticMapper` to hydrate semantic layer from:
- Existing episodic memory (ChromaDB entries tagged as task/meeting/commitment)
- M365 connector data (Outlook tasks, Calendar meetings, Teams threads)
- Agent-generated records (BuilderAgent commits, ArchitectAgent reviews)

```python
class SemanticMapper:
    async def bootstrap_from_episodic(self, store: SemanticStore) -> int:
        """Scan ChromaDB for task/meeting/commitment entries, insert into semantic store.
        
        Returns: count of entities migrated.
        """
    
    async def sync_m365_to_semantic(self, connectors: list[M365Connector]) -> int:
        """Fetch current tasks/meetings from M365, insert/update in semantic store."""
```

**Tests:** `tests/test_semantic_mapper.py` (2 tests)
- Bootstrap from episodic: count matches ChromaDB task entries
- M365 sync: new meetings from Outlook appear in store

### Section 5: Query Router & APIs

**File:** `src/probos/routers/work.py` (extend existing)

Add endpoints:
```python
@router.get("/work/tasks")
async def list_tasks(completed: bool = False) -> list[Task]:
    """List tasks for daily planning UI."""

@router.get("/work/commitments")
async def list_commitments(status: str = "open") -> list[Commitment]:
    """What the assistant committed to deliver."""

@router.get("/work/search")
async def search_work(query: str) -> list[SemanticEntity]:
    """Full-text search across all work semantics."""

@router.post("/work/link")
async def link_entities(source_id: str, target_ids: list[str], link_type: str) -> dict:
    """Create cross-references for delegation reasoning."""
```

**Tests:** `tests/test_work_routers.py` (2 tests)
- GET /work/tasks returns incomplete tasks
- POST /work/link creates valid cross-references

### Section 6: Acceptance Criteria & Gate

**Test Expectations:**
- `test_semantic_store.py`: 3 tests
- `test_session_manager.py`: 2 tests
- `test_semantic_mapper.py`: 2 tests
- `test_work_routers.py`: 2 tests
- **Total: 9 new tests**

**Dependency Gate:** Requires AD-749 (M365 connectors) to be shipped first for bootstrap-from-m365 path.

**Integration Check:** SemanticStore must be instantiated in runtime.py after AD-749's M365 bootstrap, before Yeo/crew reasoning loops.

**Type Annotations:** All public methods fully typed.

**Engineering Principles:**
- (S) SemanticStore: single responsibility (persistence/query)
- (O) SemanticEntity: open for extension (new entity types)
- (L) All entity types implement consistent contract
- (I) Depend on SemanticStore interface, not SQLite directly
- (D) SemanticStore injected into agents, not imported

**Completion Signal:**
- All 9 tests passing
- Bootstrap from episodic + M365 verified (count matches)
- `/work/tasks` + `/work/search` endpoints functional
- Session continuity contract honored (restore after simulated crash)
- Includes migration and fallback behavior for pre-existing data.
- For free leverage documented: semantic retrieval builds on existing ChromaDB/episodic plumbing.
- Captain invariant appears in acceptance checks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
