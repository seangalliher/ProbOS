# AD-595b: Naming Ceremony → BilletRegistry Integration

**Issue:** TBD (create issue after review)
**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-595a (BilletRegistry must be built first)
**Files:** `src/probos/ontology/billet_registry.py`, `src/probos/cognitive/orientation.py`, `src/probos/agent_onboarding.py`, `src/probos/startup/finalize.py`, `tests/test_ad595b_naming_billet.py` (NEW)

## Problem

The naming ceremony (`run_naming_ceremony()` in `agent_onboarding.py`) assigns callsigns and updates `CallsignRegistry` + ontology, but never notifies the `BilletRegistry`. The billet system (AD-595a) has `_emit()` and event infrastructure, but no `assign()` method to call it. This means:

1. No `BILLET_ASSIGNED` event fires when an agent gets commissioned
2. Agent orientation doesn't include their billet title (e.g., "Chief Engineer")
3. The Watch Bill (roster) lacks callsign data from the naming ceremony

After AD-595a establishes the read-side BilletRegistry, this AD adds the write-side `assign()` method and wires it into the existing onboarding flow so billet assignment and naming are coupled.

## Design

Three changes:

1. **BilletRegistry.assign()** — The write-side method deferred from AD-595a. Validates the post exists, emits `BILLET_ASSIGNED`. Idempotent: calling assign() with the same agent+callsign is a no-op.
2. **Naming ceremony + warm boot** — After callsign is assigned and identity is issued, call `billet_registry.assign()` to emit `BILLET_ASSIGNED`.
3. **Orientation** — `OrientationContext` gains a `billet_title: str` field so agents know their billet at orientation time.

**NOT changing:**
- The naming ceremony prompt or LLM call — unchanged
- CallsignRegistry — still the callsign→agent_type lookup
- DepartmentService — still the underlying data store (assign() does not duplicate data)
- The warm-boot flow itself — unchanged, but billet assignment is added after identity issuance

**Ordering in `wire_agent()`:** Billet assignment goes AFTER identity issuance (line ~296+), not after callsign sync. This is because the birth certificate needs to be issued first — billet assignment is a notification event, not a data-critical step.

---

## Section 0: Add `assign()` method to BilletRegistry

**File:** `src/probos/ontology/billet_registry.py`

This is the core mutator deferred from AD-595a. It validates the post exists via `_dept.get_post()`, then emits `BILLET_ASSIGNED`. It does NOT write to DepartmentService — the ontology already has the assignment from organization.yaml / `wire_agent()`. BilletRegistry.assign() is purely event emission + validation.

**Idempotency contract:** `assign()` is idempotent — calling it twice with the same `(post_id, agent_type, callsign)` emits the event both times. This is safe because `BILLET_ASSIGNED` consumers must be idempotent (it's an event notification, not a state mutation). The warm-boot and cold-start paths may both call assign() for the same agent in edge cases; this must not error.

Add after the `refresh()` method (line 156), before `_emit()`:

```python
    def assign(
        self,
        post_id: str,
        agent_type: str,
        callsign: str = "",
    ) -> bool:
        """Notify that an agent has been assigned to a billet.

        Validates the post exists, then emits BILLET_ASSIGNED. Does NOT
        mutate DepartmentService — the ontology already has the assignment.
        This is purely event emission for downstream consumers.

        Idempotent: safe to call multiple times for the same agent.

        If ``callsign`` is empty, falls back to the assignment's stored
        callsign from DepartmentService (set by naming ceremony or
        organization.yaml seed). This avoids polluting the event stream
        with agent_type strings when the real callsign is available.

        Parameters
        ----------
        post_id : str
            The post identifier from organization.yaml (e.g., "chief_engineer").
        agent_type : str
            The agent type filling the billet.
        callsign : str
            The agent's current callsign. Empty string means "look up from
            the assignment's stored callsign."

        Returns
        -------
        bool
            True if the post exists and event was emitted, False otherwise.
        """
        post = self._dept.get_post(post_id)
        if not post:
            logger.warning(
                "BilletRegistry.assign: unknown post_id %r for agent %s",
                post_id, agent_type,
            )
            return False

        # AD-595b: Fall back to the assignment's stored callsign if caller
        # didn't provide one, rather than polluting events with agent_type.
        if not callsign:
            assignment = self._dept.get_assignment_for_agent(agent_type)
            callsign = assignment.callsign if assignment else ""

        self._emit(EventType.BILLET_ASSIGNED, {
            "billet_id": post_id,
            "title": post.title,
            "department": post.department_id,
            "agent_type": agent_type,
            "callsign": callsign,
        })
        return True
```

---

## Section 1: Add `billet_title` field to OrientationContext

**File:** `src/probos/cognitive/orientation.py`

Add a `billet_title` field to the `OrientationContext` dataclass. Place it after the `post` field (line 31). Note: `OrientationContext` is `@dataclass(frozen=True)` (line 25).

Current (lines 30–35):
```python
    callsign: str = ""
    post: str = ""  # role title
    department: str = ""
    department_chief: str = ""
    reports_to: str = ""
    rank: str = ""
```

Change to:
```python
    callsign: str = ""
    post: str = ""  # role title
    billet_title: str = ""  # AD-595b: formal billet title from BilletRegistry
    department: str = ""
    department_chief: str = ""
    reports_to: str = ""
    rank: str = ""
```

---

## Section 2: Wire BilletRegistry into AgentOnboardingService

**File:** `src/probos/agent_onboarding.py`

### 2a: Add `_billet_registry` attribute and public setter

Add a late-bound attribute after `self._skill_bridge` (line 78):

```python
        self._billet_registry: Any = None  # AD-595b: Late-bound
```

Add a public setter method after the existing setter methods (after `set_skill_bridge`, around line 94):

```python
    def set_billet_registry(self, registry: Any) -> None:
        """AD-595b: Set billet registry (public setter for LoD)."""
        self._billet_registry = registry
```

### 2b: Add `dataclasses` import

Add at the top of the file, with the other stdlib imports:

```python
import dataclasses
```

---

## Section 3: Populate `billet_title` in orientation

**File:** `src/probos/agent_onboarding.py`

In the orientation building block (lines 239–266), after `_ctx = self._orientation_service.build_orientation(...)` returns (line 245–259), add billet title enrichment. Place this after the `_ctx = ...` assignment and before the `if not _existing_identity_callsign:` check (line 260):

```python
                # AD-595b: Enrich orientation with billet title
                if self._billet_registry and self._ontology:
                    _post = self._ontology.get_post_for_agent(agent.agent_type)
                    if _post:
                        _holder = self._billet_registry.resolve(_post.id)
                        if _holder and _holder.title:
                            _ctx = dataclasses.replace(_ctx, billet_title=_holder.title)
```

This uses `ontology.get_post_for_agent()` (line 162 of service.py) to find the post, then `resolve()` by post_id to get the BilletHolder with the title.

---

## Section 4: Add billet assignment after identity issuance

**File:** `src/probos/agent_onboarding.py`

Billet assignment goes AFTER identity issuance (the AD-441c block, lines 268–328), not after callsign sync. This is intentional — the birth certificate should be issued first, and billet assignment is a downstream event notification.

**Exact anchor:** Place the new block immediately BEFORE the comment `# AD-427: ACM onboarding for crew agents` (line 330). The AD-441c identity try/except ends at line 328 (`except Exception as e: logger.debug("Identity resolution skipped...")`), then line 329 is blank. The new block goes at line 330 (replacing nothing — insert between the blank line and the AD-427 comment). Indent level: 8 spaces (same level as the `if self._identity_registry:` block — inside `wire_agent()`, NOT inside the identity try/except).

```python
        # AD-595b: Notify BilletRegistry of billet assignment.
        # Placed after identity issuance — billet assignment is a notification
        # event, not data-critical. Covers all paths: cold-start naming,
        # warm-boot identity restoration, and non-crew agents with posts.
        if self._billet_registry and self._ontology:
            _post = self._ontology.get_post_for_agent(agent.agent_type)
            if _post:
                _callsign = getattr(agent, 'callsign', '') or ""
                self._billet_registry.assign(_post.id, agent.agent_type, callsign=_callsign)

        # AD-427: ACM onboarding for crew agents   <-- existing line, do NOT duplicate
```

**Why a single block instead of three (cold/warm/non-crew):** The original prompt had three separate billet assignment points (2b, 2c, 2d) with a `_billet_assigned` flag to avoid double-fire. This is fragile — future code paths could miss the flag. Instead, a single block after identity covers ALL paths uniformly. The callsign is already correct at this point regardless of which path was taken (naming ceremony set it, warm boot restored it, or it's the seed default).

**Why this doesn't double-fire:** There's only one call site. `assign()` is idempotent anyway, but with a single block there's no need for the `_billet_assigned` tracking flag.

---

## Section 5: Wire BilletRegistry into onboarding in finalize

**File:** `src/probos/startup/finalize.py`

In the onboarding wiring section (lines 281–307), after the `set_skill_bridge()` call (line 306), add:

```python
    # AD-595b: Wire BilletRegistry into onboarding
    if runtime.ontology and runtime.ontology.billet_registry:
        runtime.onboarding.set_billet_registry(runtime.ontology.billet_registry)
```

**Note:** This uses `runtime.ontology.billet_registry` (the property delegate from AD-595a), NOT `runtime._billet_registry` (which doesn't exist).

---

## Section 6: Tests

**File:** `tests/test_ad595b_naming_billet.py` (NEW)

```python
"""Tests for AD-595b: Naming ceremony -> BilletRegistry integration."""

from __future__ import annotations

import dataclasses

from unittest.mock import MagicMock

from probos.cognitive.orientation import OrientationContext
from probos.events import EventType
from probos.ontology.billet_registry import BilletRegistry
from probos.ontology.models import Post, Assignment


# --- Fixtures ---

def _make_dept_service():
    """Create a minimal DepartmentService-like object with real data."""
    svc = MagicMock()
    posts = {
        "chief_engineer": Post(id="chief_engineer", title="Chief Engineer", department_id="engineering", reports_to="first_officer"),
        "chief_medical": Post(id="chief_medical", title="Chief Medical Officer", department_id="medical", reports_to="first_officer"),
    }
    assignments = {
        "engineer": Assignment(agent_type="engineer", post_id="chief_engineer", callsign="LaForge", agent_id="agent-001"),
    }
    svc.get_posts.return_value = list(posts.values())
    svc.get_post.side_effect = lambda pid: posts.get(pid)
    svc.get_post_for_agent.side_effect = lambda at: posts.get(assignments[at].post_id) if at in assignments else None
    svc.get_agents_for_post.side_effect = lambda pid: [a for a in assignments.values() if a.post_id == pid]
    svc.get_assignment_for_agent.side_effect = lambda at: assignments.get(at)
    return svc, posts, assignments


# --- BilletRegistry.assign() tests ---

class TestBilletRegistryAssign:

    def test_assign_emits_billet_assigned_event(self):
        """AD-595b: assign() emits BILLET_ASSIGNED with correct payload."""
        dept_svc, _, _ = _make_dept_service()
        events: list[tuple] = []
        registry = BilletRegistry(dept_svc, emit_event_fn=lambda et, d: events.append((et, d)))

        result = registry.assign("chief_engineer", "engineer", callsign="LaForge")

        assert result is True
        assert len(events) == 1
        et, data = events[0]
        assert et == EventType.BILLET_ASSIGNED
        assert data["billet_id"] == "chief_engineer"
        assert data["title"] == "Chief Engineer"
        assert data["department"] == "engineering"
        assert data["agent_type"] == "engineer"
        assert data["callsign"] == "LaForge"

    def test_assign_unknown_post_returns_false(self):
        """AD-595b: assign() returns False for non-existent post."""
        dept_svc, _, _ = _make_dept_service()
        events: list[tuple] = []
        registry = BilletRegistry(dept_svc, emit_event_fn=lambda et, d: events.append((et, d)))

        result = registry.assign("nonexistent_post", "engineer")

        assert result is False
        assert len(events) == 0

    def test_assign_idempotent(self):
        """AD-595b: assign() called twice emits twice (idempotent, no error)."""
        dept_svc, _, _ = _make_dept_service()
        events: list[tuple] = []
        registry = BilletRegistry(dept_svc, emit_event_fn=lambda et, d: events.append((et, d)))

        registry.assign("chief_engineer", "engineer", callsign="LaForge")
        registry.assign("chief_engineer", "engineer", callsign="LaForge")

        assert len(events) == 2  # Both succeed

    def test_assign_no_callback_no_crash(self):
        """AD-595b: assign() without event callback doesn't crash."""
        dept_svc, _, _ = _make_dept_service()
        registry = BilletRegistry(dept_svc, emit_event_fn=None)

        result = registry.assign("chief_engineer", "engineer")

        assert result is True  # Post exists, just no emission

    def test_assign_vacant_billet(self):
        """AD-595b: assign() works for billet with no prior holder."""
        dept_svc, _, _ = _make_dept_service()
        events: list[tuple] = []
        registry = BilletRegistry(dept_svc, emit_event_fn=lambda et, d: events.append((et, d)))

        result = registry.assign("chief_medical", "doctor", callsign="Bones")

        assert result is True
        assert events[0][1]["title"] == "Chief Medical Officer"

    def test_assign_empty_callsign_falls_back_to_assignment(self):
        """AD-595b: assign() with empty callsign looks up stored assignment callsign."""
        dept_svc, _, _ = _make_dept_service()
        events: list[tuple] = []
        registry = BilletRegistry(dept_svc, emit_event_fn=lambda et, d: events.append((et, d)))

        # engineer's assignment has callsign="LaForge" in the fixture
        result = registry.assign("chief_engineer", "engineer", callsign="")

        assert result is True
        assert events[0][1]["callsign"] == "LaForge"  # Fell back to assignment

    def test_assign_empty_callsign_no_assignment(self):
        """AD-595b: assign() with empty callsign and no assignment emits empty callsign."""
        dept_svc, _, _ = _make_dept_service()
        events: list[tuple] = []
        registry = BilletRegistry(dept_svc, emit_event_fn=lambda et, d: events.append((et, d)))

        # chief_medical has no assignment in the fixture
        result = registry.assign("chief_medical", "unknown_agent", callsign="")

        assert result is True
        assert events[0][1]["callsign"] == ""  # No assignment to fall back to


# --- OrientationContext tests ---

class TestOrientationContextBilletTitle:

    def test_billet_title_field_exists(self):
        """AD-595b: OrientationContext has billet_title field with empty default."""
        ctx = OrientationContext()
        assert ctx.billet_title == ""

    def test_billet_title_set_at_construction(self):
        """AD-595b: billet_title can be populated at construction."""
        ctx = OrientationContext(billet_title="Chief Engineer")
        assert ctx.billet_title == "Chief Engineer"

    def test_billet_title_via_dataclasses_replace(self):
        """AD-595b: billet_title can be set via dataclasses.replace (frozen)."""
        ctx = OrientationContext(post="chief_engineer")
        ctx2 = dataclasses.replace(ctx, billet_title="Chief Engineer")
        assert ctx2.billet_title == "Chief Engineer"
        assert ctx2.post == "chief_engineer"  # Other fields preserved


# --- Integration: billet title in orientation ---

class TestBilletTitleInOrientation:

    def test_resolve_provides_title_for_orientation(self):
        """AD-595b: BilletRegistry.resolve() returns title usable for orientation."""
        dept_svc, _, _ = _make_dept_service()
        registry = BilletRegistry(dept_svc)

        holder = registry.resolve("chief_engineer")
        assert holder is not None
        assert holder.title == "Chief Engineer"

        # Simulate what wire_agent does: enrich orientation
        ctx = OrientationContext(post="chief_engineer")
        ctx = dataclasses.replace(ctx, billet_title=holder.title)
        assert ctx.billet_title == "Chief Engineer"


# --- Onboarding setter ---

class TestOnboardingBilletRegistryWiring:

    def _make_onboarding_service(self):
        """Create AgentOnboardingService with all required kwargs mocked."""
        from probos.agent_onboarding import AgentOnboardingService
        from probos.config import SystemConfig

        return AgentOnboardingService(
            config=SystemConfig(),
            callsign_registry=MagicMock(),
            capability_registry=MagicMock(),
            gossip=MagicMock(),
            intent_bus=MagicMock(),
            trust_network=MagicMock(),
            event_log=MagicMock(),
            identity_registry=None,
            ontology=None,
            event_emitter=MagicMock(),
            llm_client=None,
            registry=MagicMock(),
            ward_room=None,
            acm=None,
        )

    def test_set_billet_registry(self):
        """AD-595b: AgentOnboardingService accepts billet registry via setter."""
        svc = self._make_onboarding_service()

        mock_reg = MagicMock()
        svc.set_billet_registry(mock_reg)
        assert svc._billet_registry is mock_reg

    def test_no_crash_without_billet_registry(self):
        """AD-595b: Onboarding works fine when billet_registry is None."""
        svc = self._make_onboarding_service()

        # _billet_registry is None by default
        assert svc._billet_registry is None
```

---

## What This Does NOT Change

- `probos reset` — no change
- `CallsignRegistry` — still callsign→agent_type lookup
- `DepartmentService` — still the data store; `assign()` doesn't write to it
- `run_naming_ceremony()` — the LLM prompt is unchanged
- `BilletRegistry.resolve()`, `get_roster()` — read-side unchanged
- The `BILLET_VACATED` event type (reserved for AD-595c)

**Follow-up:** Verify that `render_cold_start_orientation()` and `render_warm_boot_orientation()` in `orientation.py` actually reference `{billet_title}` in their templates. If not, a follow-up AD should update the templates to display the billet title to agents during orientation. The field is enriched but won't be visible to agents until the templates use it.

---

## Verification

```bash
# Targeted tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad595b_naming_billet.py -v

# AD-595a tests (must not break)
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad595a_billet_registry.py -v

# Existing onboarding tests (must not break)
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_onboarding.py -v

# Full suite
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

### PROGRESS.md
Add line:
```
AD-595b CLOSED. Naming ceremony → BilletRegistry integration. BilletRegistry.assign() method added (validate post + emit BILLET_ASSIGNED, falls back to stored callsign when caller passes empty). Single billet assignment point after identity issuance covers cold-start, warm-boot, and non-crew paths. OrientationContext gains billet_title field. 13 new tests. Depends on AD-595a.
```

### DECISIONS.md
Add entry:
```
**AD-595b: Billet assignment coupled to naming ceremony.** Added `BilletRegistry.assign()` — validates post exists, emits `BILLET_ASSIGNED`. Does NOT write to DepartmentService (ontology already has the assignment). Billet assignment placed as a single block after identity issuance (AD-441c) rather than three separate blocks (cold/warm/non-crew) with tracking flags — simpler, covers all paths uniformly, and `assign()` is idempotent. OrientationContext.billet_title added so agents know their formal billet at cognitive grounding time, enriched via `dataclasses.replace()` on the frozen dataclass.
```

### docs/development/roadmap.md
Update AD-595b status from `planned` to `complete` in the sub-AD list.
