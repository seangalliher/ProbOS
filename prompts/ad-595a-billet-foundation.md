# AD-595a: Billet Foundation — BilletRegistry with Resolution + Events

**Issue:** [#165](https://github.com/seangalliher/ProbOS/issues/165)
**Status:** Ready for builder
**Priority:** Medium
**Files:** `src/probos/ontology/billet_registry.py` (NEW), `src/probos/events.py`, `src/probos/ontology/service.py`, `src/probos/runtime.py`, `src/probos/startup/finalize.py`, `tests/test_ad595a_billet_registry.py` (NEW)

## Problem

ProbOS has the data model for billets (Posts) and their holders (Assignments) in the ontology (`src/probos/ontology/models.py`), but no authoritative resolution API. When standing orders say "report to the Chief Engineer", or a crew agent needs to DM the Operations Chief, there is no clean programmatic way to answer "who holds that billet right now?"

Existing pieces:
- `DepartmentService.get_post(post_id)` — lookup by `post_id` string (e.g., `"chief_engineer"`)
- `DepartmentService.get_assignment_for_agent(agent_type)` — reverse lookup by agent type
- `DepartmentService.wire_agent(agent_type, agent_id)` — runtime binding
- `CallsignRegistry.resolve(callsign)` — lookup by callsign string

**What's missing:**
1. Title-based resolution: `resolve("Chief Engineer")` → current holder's agent info
2. Roster snapshots: `get_roster()` → Watch Bill showing all billets and who fills them
3. Event types: `BILLET_ASSIGNED` / `BILLET_VACATED` — consumed by Counselor, ACM, standing orders

**Deferred to AD-595b:** `assign()` and `vacate()` mutators. The naming ceremony already calls `DepartmentService.update_assignment_callsign()` — AD-595b will add `BilletRegistry.assign()` that wraps this call + emits `BILLET_ASSIGNED`. True post-reassignment (changing agent_type→post_id mapping) is not needed for the naming ceremony use case; the YAML-loaded mapping is immutable at runtime.

## Design

`BilletRegistry` is a **facade** over `DepartmentService`, not a replacement. It wraps the existing ontology data model (Post, Assignment) and adds resolution + events. This follows Interface Segregation: consumers that need billet resolution depend on `BilletRegistry`, not the full `VesselOntologyService`.

**NOT creating:** SQLite persistence. Billet assignments are reconstructed from pool startup + naming ceremony on each boot — the same flow that populates the ontology today. Persistence is deferred until AD-595 proves the value.

## What This Does NOT Change

- `Post` / `Assignment` / `Department` dataclasses in `ontology/models.py` — unchanged
- `DepartmentService` methods — unchanged (BilletRegistry delegates to them)
- `VesselOntologyService` — gains one new accessor, but no API changes
- `CallsignRegistry` — unchanged (remains the callsign lookup; BilletRegistry is the billet lookup)
- `organization.yaml` — unchanged (Posts already define billets)
- `crew.yaml` — unchanged
- Agent fleet startup — unchanged (still calls `wire_agent()` through ontology)
- Naming ceremony — deferred to AD-595b

---

## Section 1: Add billet event types

**File:** `src/probos/events.py`

Add two new event types in the `EventType` enum. Place them after the existing sub-task events (after line 185, before the DAG execution group):

```python
    # Billet management (AD-595a)
    BILLET_ASSIGNED = "billet_assigned"
    BILLET_VACATED = "billet_vacated"    # Reserved for AD-595b's vacate() — added now to keep enum changes atomic with BILLET_ASSIGNED
```

---

## Section 2: Create BilletRegistry

**File:** `src/probos/ontology/billet_registry.py` (NEW)

```python
"""AD-595a: BilletRegistry — authoritative billet-to-agent resolution.

Facade over DepartmentService that adds title-based resolution, roster
snapshots, and event infrastructure for billet changes. Follows the
Navy Watch Bill model: billets are permanent positions, agents rotate.

AD-595a provides the read-side API. Mutators (assign/vacate) are added
by AD-595b when the naming ceremony is wired.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from probos.events import EventType
from probos.ontology.models import Assignment, Post

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BilletHolder:
    """Snapshot of a billet and its current holder.

    Frozen to prevent accidental mutation that drifts from DepartmentService.
    """

    billet_id: str
    title: str
    department: str
    holder_agent_type: str | None
    holder_callsign: str | None
    holder_agent_id: str | None


class BilletRegistry:
    """Authoritative Watch Bill — resolves billets to current holders.

    Wraps DepartmentService for billet queries. Does not own the data —
    DepartmentService remains the source of truth for posts and assignments.

    Parameters
    ----------
    department_service : DepartmentService
        The underlying ontology department service.
    emit_event_fn : callable, optional
        Callback ``(EventType, dict) -> None`` for billet events.
    """

    def __init__(
        self,
        department_service: Any,
        emit_event_fn: Callable[[EventType, dict[str, Any]], None] | None = None,
    ) -> None:
        self._dept = department_service
        self._emit_event_fn = emit_event_fn
        # Build title→post_id index for title-based resolution
        self._title_index: dict[str, str] = {}
        self._rebuild_title_index()

    def set_event_callback(
        self, emit_fn: Callable[[EventType, dict[str, Any]], None],
    ) -> None:
        """AD-595a: Set event emission callback (public API for late binding)."""
        self._emit_event_fn = emit_fn

    def _rebuild_title_index(self) -> None:
        """Build lowercase title → post_id lookup from current posts."""
        self._title_index = {}
        for post in self._dept.get_posts():
            title_lower = post.title.lower()
            if title_lower in self._title_index:
                logger.warning(
                    "BilletRegistry: title collision for %r (posts %s and %s) — "
                    "title resolution will return the latter",
                    post.title, self._title_index[title_lower], post.id,
                )
            self._title_index[title_lower] = post.id

    def resolve(self, title_or_id: str) -> BilletHolder | None:
        """Resolve a billet title or post_id to its current holder.

        Accepts either a post_id ("chief_engineer") or a title
        ("Chief Engineer"). Case-insensitive for titles.

        Returns None if the billet does not exist.
        Returns a BilletHolder with holder fields as None if billet
        exists but is vacant.
        """
        # Try as post_id first
        post = self._dept.get_post(title_or_id)
        if not post:
            # Try as title (case-insensitive)
            post_id = self._title_index.get(title_or_id.lower())
            if post_id:
                post = self._dept.get_post(post_id)
        if not post:
            return None

        # Find holder
        assignments = self._dept.get_agents_for_post(post.id)
        holder = assignments[0] if assignments else None

        return BilletHolder(
            billet_id=post.id,
            title=post.title,
            department=post.department_id,
            holder_agent_type=holder.agent_type if holder else None,
            holder_callsign=holder.callsign if holder else None,
            holder_agent_id=holder.agent_id if holder else None,
        )

    def resolve_agent_type(self, title_or_id: str) -> str | None:
        """Convenience: resolve a billet to just the holder's agent_type."""
        holder = self.resolve(title_or_id)
        return holder.holder_agent_type if holder else None

    def resolve_callsign(self, title_or_id: str) -> str | None:
        """Convenience: resolve a billet to the holder's callsign.

        Returns None if the billet doesn't exist OR if the billet is vacant.
        Callers that need to distinguish should use resolve() directly.
        """
        holder = self.resolve(title_or_id)
        return holder.holder_callsign if holder else None

    def get_roster(self) -> list[BilletHolder]:
        """Return the full Watch Bill — all billets with current holders."""
        roster: list[BilletHolder] = []
        for post in self._dept.get_posts():
            assignments = self._dept.get_agents_for_post(post.id)
            holder = assignments[0] if assignments else None
            roster.append(BilletHolder(
                billet_id=post.id,
                title=post.title,
                department=post.department_id,
                holder_agent_type=holder.agent_type if holder else None,
                holder_callsign=holder.callsign if holder else None,
                holder_agent_id=holder.agent_id if holder else None,
            ))
        return roster

    def get_department_roster(self, department_id: str) -> list[BilletHolder]:
        """Return Watch Bill for a single department."""
        return [b for b in self.get_roster() if b.department == department_id]

    def refresh(self) -> None:
        """Rebuild the title index from current posts.

        Call after any bulk post changes. For AD-595a, posts are immutable
        after startup — this exists as a clean extension point for future
        runtime billet creation.
        """
        self._rebuild_title_index()

    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Emit an event if the callback is set."""
        if self._emit_event_fn:
            self._emit_event_fn(event_type, data)
```

---

## Section 3: Wire BilletRegistry into VesselOntologyService

**File:** `src/probos/ontology/service.py`

### 3a: Add import and initialize BilletRegistry eagerly in `initialize()`

Add import at top of file (after existing ontology imports):

```python
from probos.ontology.billet_registry import BilletRegistry
```

Add `self._billet_registry = None` in `__init__()` (after line 50, near other instance attributes):

```python
        self._billet_registry: BilletRegistry | None = None  # AD-595a
```

In the `initialize()` method, after `self._dept = DepartmentService(...)` (around line 59), add eager construction:

```python
        # AD-595a: Build BilletRegistry eagerly (no lazy init — avoids race)
        self._billet_registry = BilletRegistry(self._dept)
```

Add a plain property accessor (no lazy init, no wrapper):

```python
    @property
    def billet_registry(self) -> "BilletRegistry | None":
        """AD-595a: Billet resolution facade."""
        return self._billet_registry
```

---

## Section 4: Wire into runtime

**File:** `src/probos/runtime.py`

### 4a: Add property delegate (no instance attribute)

Add a property near the other service properties:

```python
    @property
    def billet_registry(self) -> Any:
        """AD-595a: Billet resolution facade (delegates to ontology)."""
        if self.ontology is None:
            return None
        return self.ontology.billet_registry
```

No `self._billet_registry` instance attribute — the property delegates to `ontology.billet_registry` directly. This avoids duplicate references and private-attr writes from outside the class.

**File:** `src/probos/startup/finalize.py`

### 4b: Wire event callback in finalize phase

Add after the ontology-related wiring in finalize.py (after the existing trust dampening wiring block, around line 90):

```python
    # --- AD-595a: Wire BilletRegistry event callback ---
    if runtime.ontology and runtime.ontology.billet_registry:
        runtime.ontology.billet_registry.set_event_callback(runtime.emit_event)
        logger.info("AD-595a: BilletRegistry wired")
```

---

## Section 5: Tests

**File:** `tests/test_ad595a_billet_registry.py` (NEW)

```python
"""Tests for AD-595a: BilletRegistry — billet resolution + events."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from probos.events import EventType
from probos.ontology.models import Post, Assignment, Department
from probos.ontology.departments import DepartmentService
from probos.ontology.billet_registry import BilletRegistry, BilletHolder


# --- Fixtures ---

@pytest.fixture
def dept_service():
    """Create a DepartmentService with test departments, posts, and assignments."""
    departments = {
        "engineering": Department(id="engineering", name="Engineering", description=""),
        "science": Department(id="science", name="Science", description=""),
    }
    posts = {
        "chief_engineer": Post(
            id="chief_engineer",
            title="Chief Engineer",
            department_id="engineering",
            reports_to="first_officer",
            tier="crew",
        ),
        "engineering_officer": Post(
            id="engineering_officer",
            title="Engineering Officer",
            department_id="engineering",
            reports_to="chief_engineer",
            tier="crew",
        ),
        "chief_science": Post(
            id="chief_science",
            title="Chief Science Officer",
            department_id="science",
            reports_to="first_officer",
            tier="crew",
        ),
        "vacant_post": Post(
            id="vacant_post",
            title="Vacant Post",
            department_id="science",
            reports_to="chief_science",
            tier="crew",
        ),
    }
    assignments = {
        "engineer": Assignment(
            agent_type="engineer",
            post_id="chief_engineer",
            callsign="LaForge",
            agent_id="agent-eng-001",
        ),
        "engineering_officer": Assignment(
            agent_type="engineering_officer",
            post_id="engineering_officer",
            callsign="Torres",
            agent_id="agent-eng-002",
        ),
        "number_one": Assignment(
            agent_type="number_one",
            post_id="chief_science",
            callsign="Meridian",
            agent_id="agent-sci-001",
        ),
        # vacant_post has no assignment
    }
    return DepartmentService(departments, posts, assignments)


@pytest.fixture
def registry(dept_service):
    """BilletRegistry with mock event emitter."""
    mock_emit = MagicMock()
    return BilletRegistry(dept_service, emit_event_fn=mock_emit)


# --- Resolution tests ---

class TestBilletResolution:

    def test_resolve_by_post_id(self, registry):
        """Resolve by post_id returns correct holder."""
        result = registry.resolve("chief_engineer")
        assert result is not None
        assert result.billet_id == "chief_engineer"
        assert result.title == "Chief Engineer"
        assert result.holder_callsign == "LaForge"
        assert result.holder_agent_type == "engineer"

    def test_resolve_by_title(self, registry):
        """Resolve by title (case-insensitive) returns correct holder."""
        result = registry.resolve("Chief Engineer")
        assert result is not None
        assert result.holder_callsign == "LaForge"

    def test_resolve_by_title_case_insensitive(self, registry):
        """Title resolution is case-insensitive."""
        result = registry.resolve("chief engineer")
        assert result is not None
        assert result.holder_callsign == "LaForge"

    def test_resolve_vacant_billet(self, registry):
        """Vacant billet returns BilletHolder with None holder fields."""
        result = registry.resolve("vacant_post")
        assert result is not None
        assert result.billet_id == "vacant_post"
        assert result.holder_agent_type is None
        assert result.holder_callsign is None
        assert result.holder_agent_id is None

    def test_resolve_nonexistent_billet(self, registry):
        """Nonexistent billet returns None."""
        result = registry.resolve("nonexistent")
        assert result is None

    def test_resolve_agent_type(self, registry):
        """Convenience method returns just the agent_type."""
        assert registry.resolve_agent_type("Chief Engineer") == "engineer"

    def test_resolve_callsign(self, registry):
        """Convenience method returns just the callsign."""
        assert registry.resolve_callsign("Chief Engineer") == "LaForge"

    def test_resolve_agent_type_nonexistent(self, registry):
        """Convenience returns None for unknown billet."""
        assert registry.resolve_agent_type("nonexistent") is None


# --- Roster tests ---

class TestBilletRoster:

    def test_get_roster_returns_all_billets(self, registry):
        """Full roster includes all billets."""
        roster = registry.get_roster()
        assert len(roster) == 4
        ids = {b.billet_id for b in roster}
        assert "chief_engineer" in ids
        assert "vacant_post" in ids

    def test_get_roster_includes_vacant(self, registry):
        """Roster includes vacant billets with None holder."""
        roster = registry.get_roster()
        vacant = next(b for b in roster if b.billet_id == "vacant_post")
        assert vacant.holder_agent_type is None

    def test_get_department_roster(self, registry):
        """Department roster filters correctly."""
        eng_roster = registry.get_department_roster("engineering")
        assert len(eng_roster) == 2
        assert all(b.department == "engineering" for b in eng_roster)

    def test_get_department_roster_empty(self, registry):
        """Empty department returns empty list."""
        assert registry.get_department_roster("nonexistent") == []


# --- Event tests ---

class TestBilletEvents:

    def test_set_event_callback(self, dept_service):
        """set_event_callback wires the callback."""
        reg = BilletRegistry(dept_service)
        mock_emit = MagicMock()
        reg.set_event_callback(mock_emit)
        assert reg._emit_event_fn is mock_emit

    def test_no_crash_without_callback(self, dept_service):
        """No crash when emit_event_fn is None."""
        reg = BilletRegistry(dept_service, emit_event_fn=None)
        # _emit should not raise
        reg._emit(EventType.BILLET_ASSIGNED, {"test": True})


# --- BilletHolder dataclass ---

class TestBilletHolder:

    def test_billet_holder_fields(self):
        """BilletHolder has expected fields."""
        bh = BilletHolder(
            billet_id="test",
            title="Test",
            department="eng",
            holder_agent_type="agent",
            holder_callsign="Name",
            holder_agent_id="id-1",
        )
        assert bh.billet_id == "test"
        assert bh.holder_callsign == "Name"

    def test_billet_holder_is_frozen(self):
        """BilletHolder is immutable (frozen dataclass)."""
        bh = BilletHolder(
            billet_id="test",
            title="Test",
            department="eng",
            holder_agent_type="agent",
            holder_callsign="Name",
            holder_agent_id="id-1",
        )
        with pytest.raises(AttributeError):
            bh.holder_callsign = "Changed"


# --- Refresh ---

class TestBilletRefresh:

    def test_refresh_rebuilds_title_index(self, dept_service):
        """refresh() rebuilds the title index from current posts."""
        reg = BilletRegistry(dept_service)
        # Title index should already work
        assert reg.resolve("Chief Engineer") is not None
        # Simulate a new post being added to the underlying service
        dept_service._posts["new_post"] = Post(
            id="new_post",
            title="New Post",
            department_id="engineering",
            reports_to="chief_engineer",
            tier="crew",
        )
        # Before refresh, title resolution doesn't find the new post
        assert reg.resolve("New Post") is None
        # After refresh, it does
        reg.refresh()
        assert reg.resolve("New Post") is not None
        assert reg.resolve("New Post").billet_id == "new_post"
```

---

## Section 6: Attribute name verified

The `DepartmentService` attribute in `VesselOntologyService.__init__` is `self._dept` (service.py:53). Section 3 already uses the correct name.

---

## Verification

```bash
# Targeted tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad595a_billet_registry.py -v

# Full suite
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

### PROGRESS.md
Add line:
```
AD-595a CLOSED. BilletRegistry — read-side facade over DepartmentService adding title-based resolution (case-insensitive), roster snapshots (Watch Bill), and BILLET_ASSIGNED/BILLET_VACATED event types. BilletHolder is frozen dataclass. Eagerly initialized in VesselOntologyService.initialize(). 23 posts from organization.yaml available as billets. Mutators (assign/vacate) deferred to AD-595b. 17 new tests. Issue #165.
```

### DECISIONS.md
Add entry:
```
**AD-595a: BilletRegistry as read-side facade, not replacement.** Built BilletRegistry as a thin layer over existing DepartmentService (ontology) rather than a separate data store. Posts (billets) and Assignments (holders) already exist in organization.yaml/DepartmentService — adding a parallel system would create inconsistency. BilletRegistry adds: title-based resolution, roster snapshots, event types. Mutators (assign/vacate) deferred to AD-595b — they require extending DepartmentService with runtime reassignment, which is a separate concern. BilletHolder is frozen dataclass (immutable snapshot). No SQLite persistence — billet assignments are reconstructed from pool startup on each boot, same as today. Persistence deferred until agent mobility proves the need. Establishes pattern for ontology facades: read-side resolution + events through a focused class, write-side delegated to underlying service. AD-595b will extend this with mutators.
```

### docs/development/roadmap.md
Update AD-595a status from `planned` to `complete` in the sub-AD list.
