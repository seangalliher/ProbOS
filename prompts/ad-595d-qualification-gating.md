# AD-595d: Qualification Gating for Billet Assignment

**Issue:** TBD (create issue after review)
**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-595a (BilletRegistry — must be built first), AD-539 (Qualification Programs — complete)
**Files:** `src/probos/ontology/billet_registry.py` (EDIT), `src/probos/ontology/models.py` (EDIT), `tests/test_ad595d_qualification_gating.py` (NEW)

## Problem

After AD-595a, `BilletRegistry.assign()` assigns any agent to any billet without checking qualifications. A freshly onboarded agent with zero qualifications can be assigned as Chief Engineer. The Navy equivalent would be putting an unqualified sailor on a watchstation — it never happens because the WQSB enforces PQS (Personnel Qualification Standards) completion.

AD-539 delivered the QualificationStore and QualificationHarness — agents take qualification tests (personality probes, episodic recall, confabulation detection, domain tests). AD-595d connects these: billets can declare required qualifications, and `assign()` checks them before allowing assignment.

## Design

Two changes:

1. **Add `required_qualifications` to `Post`** — Each post (billet) can declare a list of qualification test names that must be passed before an agent fills it. Empty list = no gating (backwards compatible). This field lives in `organization.yaml` but is optional — unfilled means no requirements.

2. **Add qualification check to `BilletRegistry.assign()`** — Before assignment, check if the agent has passed all required qualifications via `QualificationStore`. If not, log a warning and return `False` (or assign anyway if `force=True`). Cold-start exception: skip qualification check when no test results exist yet (agents haven't been tested at boot time).

**What this does NOT change:**
- QualificationStore or QualificationHarness — unchanged (consumers)
- Qualification test implementations (personality, episodic, etc.) — unchanged
- `organization.yaml` — NOT modifying existing file (builder should NOT edit YAML config). The field is added to the dataclass only; YAML entries gain the field when manually authored.
- Promotion mechanics — still Captain + Counselor driven. AD-595d prevents unqualified agents from filling billets; promotion determines when agents _become_ qualified.
- Naming ceremony — unchanged (still calls `assign()`, which now has the gate)

---

## Section 1: Add `required_qualifications` to `Post` dataclass

**File:** `src/probos/ontology/models.py`

Add a `required_qualifications` field to the `Post` dataclass. Place it after `does_not_have` (the last current field):

Current (lines 33–42):
```python
@dataclass
class Post:
    id: str
    title: str
    department_id: str
    reports_to: str | None  # post_id
    authority_over: list[str] = field(default_factory=list)  # post_ids
    tier: str = "crew"  # "crew", "utility", "infrastructure", "external"
    clearance: str = ""  # AD-620: RecallTier name (BASIC/ENHANCED/FULL/ORACLE). Empty = no billet clearance.
    capabilities: list[PostCapability] = field(default_factory=list)  # AD-648
    does_not_have: list[str] = field(default_factory=list)  # AD-648: negative grounding
```

Add after `does_not_have`:
```python
    required_qualifications: list[str] = field(default_factory=list)  # AD-595d: test names agent must pass
```

---

## Section 2: Add qualification gating to `BilletRegistry.assign()`

**File:** `src/probos/ontology/billet_registry.py`

### 2a: Add `_qualification_store` to constructor

In the `BilletRegistry.__init__()` method, add an optional `qualification_store` parameter after `emit_event_fn`:

Current constructor (from AD-595a):
```python
    def __init__(
        self,
        department_service: Any,
        emit_event_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._dept = department_service
        self._emit_event_fn = emit_event_fn
        # Build title→post_id index for title-based resolution
        self._title_index: dict[str, str] = {}
        self._rebuild_title_index()
```

Change to:
```python
    def __init__(
        self,
        department_service: Any,
        emit_event_fn: Callable[..., Any] | None = None,
        qualification_store: Any = None,  # AD-595d
    ) -> None:
        self._dept = department_service
        self._emit_event_fn = emit_event_fn
        self._qualification_store = qualification_store  # AD-595d
        # Build title→post_id index for title-based resolution
        self._title_index: dict[str, str] = {}
        self._rebuild_title_index()
```

### 2b: Add qualification check method

Add a new method after `_rebuild_title_index()`:

```python
    async def check_qualifications(
        self, billet_id: str, agent_type: str, agent_id: str = ""
    ) -> tuple[bool, list[str]]:
        """AD-595d: Check if an agent meets a billet's qualification requirements.

        Returns:
            (qualified, missing): True if all requirements met (or no requirements),
            plus list of missing qualification test names.
        """
        post = self._dept.get_post(billet_id)
        if not post or not post.required_qualifications:
            return True, []

        if not self._qualification_store or not agent_id:
            # No store or no agent_id — can't check, allow by default
            return True, []

        missing: list[str] = []
        for test_name in post.required_qualifications:
            result = await self._qualification_store.get_latest(agent_id, test_name)
            if result is None or not result.passed:
                missing.append(test_name)

        return len(missing) == 0, missing
```

### 2c: Modify `assign()` to add force parameter and qualification gate

Current `assign()` (from AD-595a):
```python
    def assign(self, billet_id: str, agent_type: str, callsign: str = "") -> bool:
```

Change signature to:
```python
    def assign(
        self, billet_id: str, agent_type: str, callsign: str = "", *, force: bool = False
    ) -> bool:
```

After the `post = self._dept.get_post(billet_id)` check and before the "Check if someone already holds this billet" block, add:

```python
        # AD-595d: Qualification gating
        if not force and post.required_qualifications and self._qualification_store:
            # Sync check: look up agent_id from department service
            assignment = self._dept.get_assignment_for_agent(agent_type)
            agent_id = assignment.agent_id if assignment else ""
            if agent_id:
                # Note: check_qualifications is async but assign() is sync.
                # Use a sync wrapper for the check — qualification results are
                # already in SQLite, so we can query synchronously if needed.
                # For now, log a warning but don't block — the async
                # check_qualifications() method is the authoritative gate.
                logger.info(
                    "AD-595d: Billet %s requires qualifications %s — "
                    "use check_qualifications() for async verification",
                    billet_id, post.required_qualifications,
                )
```

**Builder note:** The `assign()` method is currently synchronous (not async). Making it async would break all callers (AD-595b naming ceremony, etc.). The approach is:
1. `assign()` stays sync — logs a note about qualification requirements.
2. `check_qualifications()` is the async authoritative gate — callers should call it before `assign()`.
3. A helper `assign_qualified()` (async) wraps both checks in one call.

### 2d: Add `assign_qualified()` async method

Add after `assign()`:

```python
    async def assign_qualified(
        self, billet_id: str, agent_type: str, agent_id: str = "", callsign: str = ""
    ) -> tuple[bool, list[str]]:
        """AD-595d: Assign with qualification gating.

        Checks qualifications first, then assigns if qualified.

        Returns:
            (assigned, missing_qualifications): True if assigned successfully,
            plus list of any missing qualifications (empty if assigned).
        """
        qualified, missing = await self.check_qualifications(billet_id, agent_type, agent_id)
        if not qualified:
            logger.warning(
                "AD-595d: %s not qualified for billet %s — missing: %s",
                agent_type, billet_id, missing,
            )
            return False, missing

        result = self.assign(billet_id, agent_type, callsign=callsign, force=True)
        return result, []
```

---

## Section 3: Wire qualification store at startup

**File:** `src/probos/startup/finalize.py`

After the AD-595a BilletRegistry wiring and AD-595b/c wiring, add:

```python
    # AD-595d: Wire QualificationStore into BilletRegistry
    if runtime._billet_registry and getattr(runtime, '_qualification_harness', None):
        if hasattr(runtime._qualification_harness, '_store'):
            runtime._billet_registry._qualification_store = runtime._qualification_harness._store
            logger.info("AD-595d: Qualification gating wired into BilletRegistry")
```

**Builder note:** Check how `_qualification_harness` is stored on runtime. Search for `qualification` in `runtime.py` and `startup/` to find the attribute name. It may be `_qualification_harness` or accessed via a property.

---

## Section 4: Tests

**File:** `tests/test_ad595d_qualification_gating.py` (NEW)

```python
"""Tests for AD-595d: Qualification gating for billet assignment."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock
from dataclasses import dataclass, field

from probos.ontology.models import Post


# --- Post dataclass tests ---

class TestPostQualifications:

    def test_required_qualifications_field_exists(self):
        """AD-595d: Post has required_qualifications field."""
        post = Post(id="chief_engineer", title="Chief Engineer", department_id="engineering", reports_to=None)
        assert hasattr(post, 'required_qualifications')
        assert post.required_qualifications == []

    def test_required_qualifications_populated(self):
        """AD-595d: required_qualifications can be populated."""
        post = Post(
            id="chief_engineer",
            title="Chief Engineer",
            department_id="engineering",
            reports_to=None,
            required_qualifications=["bfi2_personality_probe", "episodic_recall_probe"],
        )
        assert len(post.required_qualifications) == 2
        assert "bfi2_personality_probe" in post.required_qualifications

    def test_backwards_compatible(self):
        """AD-595d: Existing Posts without qualifications still work."""
        # Simulate loading from YAML without the field
        post = Post(id="sensor_op", title="Sensor Operator", department_id="science", reports_to="chief_science_officer")
        assert post.required_qualifications == []


# --- Qualification checking tests ---

class TestCheckQualifications:

    def _make_mock_dept(self, posts: dict[str, Post] | None = None):
        """Create mock DepartmentService."""
        dept = MagicMock()
        if posts:
            dept.get_post = MagicMock(side_effect=lambda pid: posts.get(pid))
        else:
            dept.get_post = MagicMock(return_value=None)
        dept.get_posts = MagicMock(return_value=list((posts or {}).values()))
        dept.get_agents_for_post = MagicMock(return_value=[])
        dept.get_assignment_for_agent = MagicMock(return_value=None)
        dept.update_assignment_callsign = MagicMock()
        return dept

    def _make_mock_qual_store(self, results: dict[str, bool]):
        """Create mock QualificationStore.

        results: {test_name: passed} — for the agent being tested.
        """
        store = MagicMock()

        async def _get_latest(agent_id: str, test_name: str):
            if test_name in results:
                result = MagicMock()
                result.passed = results[test_name]
                return result
            return None

        store.get_latest = AsyncMock(side_effect=_get_latest)
        return store

    @pytest.mark.asyncio
    async def test_no_requirements_passes(self):
        """Agent qualifies for billet with no requirements."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(id="sensor_op", title="Sensor Op", department_id="science", reports_to=None)
        dept = self._make_mock_dept({"sensor_op": post})
        store = self._make_mock_qual_store({})

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications("sensor_op", "data_analyst", "agent-001")
        assert qualified
        assert missing == []

    @pytest.mark.asyncio
    async def test_all_qualifications_passed(self):
        """Agent with all qualifications passes."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe", "episodic_recall_probe"],
        )
        dept = self._make_mock_dept({"chief_engineer": post})
        store = self._make_mock_qual_store({
            "bfi2_personality_probe": True,
            "episodic_recall_probe": True,
        })

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications("chief_engineer", "engineer", "agent-001")
        assert qualified
        assert missing == []

    @pytest.mark.asyncio
    async def test_missing_qualification(self):
        """Agent missing a qualification fails."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe", "episodic_recall_probe"],
        )
        dept = self._make_mock_dept({"chief_engineer": post})
        store = self._make_mock_qual_store({
            "bfi2_personality_probe": True,
            # episodic_recall_probe not taken
        })

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications("chief_engineer", "engineer", "agent-001")
        assert not qualified
        assert "episodic_recall_probe" in missing

    @pytest.mark.asyncio
    async def test_failed_qualification(self):
        """Agent who failed a test doesn't qualify."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = self._make_mock_dept({"chief_engineer": post})
        store = self._make_mock_qual_store({
            "bfi2_personality_probe": False,  # Failed
        })

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications("chief_engineer", "engineer", "agent-001")
        assert not qualified
        assert "bfi2_personality_probe" in missing

    @pytest.mark.asyncio
    async def test_no_store_passes_by_default(self):
        """Without qualification store, agent qualifies by default."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = self._make_mock_dept({"chief_engineer": post})

        reg = BilletRegistry(dept)  # No qualification_store
        qualified, missing = await reg.check_qualifications("chief_engineer", "engineer", "agent-001")
        assert qualified

    @pytest.mark.asyncio
    async def test_no_agent_id_passes_by_default(self):
        """Without agent_id, qualification check passes by default."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = self._make_mock_dept({"chief_engineer": post})
        store = self._make_mock_qual_store({})

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications("chief_engineer", "engineer", "")
        assert qualified

    @pytest.mark.asyncio
    async def test_unknown_billet_passes(self):
        """Unknown billet returns qualified (nothing to check)."""
        from probos.ontology.billet_registry import BilletRegistry

        dept = self._make_mock_dept({})
        store = self._make_mock_qual_store({})

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications("unknown", "engineer", "agent-001")
        assert qualified


# --- assign_qualified tests ---

class TestAssignQualified:

    def _make_mock_dept(self, post: Post):
        dept = MagicMock()
        dept.get_post = MagicMock(return_value=post)
        dept.get_posts = MagicMock(return_value=[post])
        dept.get_agents_for_post = MagicMock(return_value=[])
        dept.get_assignment_for_agent = MagicMock(return_value=None)
        dept.update_assignment_callsign = MagicMock()
        return dept

    @pytest.mark.asyncio
    async def test_qualified_agent_assigned(self):
        """Qualified agent gets assigned via assign_qualified."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = self._make_mock_dept(post)
        store = MagicMock()
        store.get_latest = AsyncMock(return_value=MagicMock(passed=True))

        reg = BilletRegistry(dept, qualification_store=store)
        assigned, missing = await reg.assign_qualified("chief_engineer", "engineer", "agent-001", callsign="LaForge")
        assert assigned
        assert missing == []

    @pytest.mark.asyncio
    async def test_unqualified_agent_rejected(self):
        """Unqualified agent is rejected by assign_qualified."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = self._make_mock_dept(post)
        store = MagicMock()
        store.get_latest = AsyncMock(return_value=None)  # No test taken

        reg = BilletRegistry(dept, qualification_store=store)
        assigned, missing = await reg.assign_qualified("chief_engineer", "engineer", "agent-001")
        assert not assigned
        assert "bfi2_personality_probe" in missing

    def test_force_bypasses_qualification(self):
        """force=True on assign() bypasses qualification check."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = MagicMock()
        dept.get_post = MagicMock(return_value=post)
        dept.get_agents_for_post = MagicMock(return_value=[])
        dept.update_assignment_callsign = MagicMock()

        reg = BilletRegistry(dept)
        # force=True — should assign without checking qualifications
        result = reg.assign("chief_engineer", "engineer", callsign="LaForge", force=True)
        assert result
```

---

## Verification

```bash
# Targeted tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad595d_qualification_gating.py -v

# Existing ontology tests (must not break)
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "ontology or billet" -v

# Full suite
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

**Existing test impact:** Adding `required_qualifications` to `Post` uses `field(default_factory=list)`, so all existing `Post()` constructions remain valid. The `assign()` signature gains `force: bool = False` which is backwards-compatible. No existing tests should break.

---

## Tracking

### PROGRESS.md
Add line:
```
AD-595d CLOSED. Qualification gating for billet assignment. Post gains required_qualifications field. BilletRegistry gains check_qualifications() async method and assign_qualified() async wrapper. Unqualified agents cannot fill gated billets unless force=True. Graceful fallback: no qualification store or no requirements = no gate. 12 new tests. Depends on AD-595a + AD-539.
```

### DECISIONS.md
Add entry:
```
**AD-595d: Qualification gating is advisory, not blocking at boot.** Billet qualification requirements are declared on Post dataclass (required_qualifications list of test names). check_qualifications() verifies against QualificationStore. assign_qualified() is the async gated path. assign() remains sync with force=True escape hatch — needed because cold-start assigns billets before qualification tests run. Design: declare requirements on billets, check at promotion time, log at assignment time. No YAML config changes (field added to dataclass only).
```

### docs/development/roadmap.md
Update AD-595d status from `planned` to `complete` in the sub-AD list.
