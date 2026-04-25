# AD-595d: Qualification-Aware Billet Assignment

**Issue:** TBD (create issue after review)
**Status:** Ready for review (v2)
**Priority:** Medium
**Depends:** AD-595a (BilletRegistry — complete), AD-539 (Qualification Programs — complete)
**Files:** `src/probos/ontology/billet_registry.py` (EDIT), `src/probos/ontology/models.py` (EDIT), `src/probos/startup/finalize.py` (EDIT), `tests/test_ad595d_qualification_gating.py` (NEW)

## Problem

After AD-595a/b, `BilletRegistry.assign()` assigns any agent to any billet without checking qualifications. A freshly onboarded agent with zero qualifications can be assigned as Chief Engineer. The Navy equivalent would be putting an unqualified sailor on a watchstation — it never happens because the WQSB enforces PQS (Personnel Qualification Standards) completion.

AD-539 delivered the QualificationStore and QualificationHarness — agents take qualification tests (personality probes, episodic recall, confabulation detection, domain tests). AD-595d connects these: billets can declare required qualifications, and `BilletRegistry` gains methods to check and enforce them.

## Scope — Data Model + Check API Only

**AD-595d adds:**
1. `required_qualifications` field on `Post` dataclass
2. `check_qualifications()` async method on `BilletRegistry`
3. `assign_qualified()` async method on `BilletRegistry` (check + assign in one call)
4. `set_qualification_store()` public setter on `BilletRegistry`
5. Startup wiring to connect `QualificationStore` → `BilletRegistry`

**AD-595d does NOT change:**
- `assign()` — stays sync, unconditional, no `force` parameter. It's a notification method, not a gate.
- AD-595b's call site in `agent_onboarding.py` — still calls `assign()` unconditionally.
- QualificationStore or QualificationHarness — unchanged (consumers).
- `organization.yaml` — NOT modifying existing file. The field is added to the dataclass only.

**Why no production gate yet:** At cold start, no agent has taken any qualification test. Gating at `assign()` time would block all billet assignments on first boot. The gate belongs in the promotion/assignment workflow (future AD-595e) where `allow_untested` can be toggled based on context. AD-595d ships the data model and check API so that future ADs can consume them.

**Future AD-595e:** Wire `assign_qualified()` into the promotion workflow when Counselor/Captain promotion lands. THAT AD enforces the gate in production.

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

## Section 2: Add qualification methods to `BilletRegistry`

**File:** `src/probos/ontology/billet_registry.py`

### 2a: Add `_qualification_store` to constructor

In the `BilletRegistry.__init__()` method, add an optional `qualification_store` parameter after `emit_event_fn`:

Current constructor:
```python
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
```

Change to:
```python
    def __init__(
        self,
        department_service: Any,
        emit_event_fn: Callable[[EventType, dict[str, Any]], None] | None = None,
        qualification_store: "QualificationStore | None" = None,  # AD-595d
    ) -> None:
        self._dept = department_service
        self._emit_event_fn = emit_event_fn
        self._qualification_store: "QualificationStore | None" = qualification_store  # AD-595d
        # Build title→post_id index for title-based resolution
        self._title_index: dict[str, str] = {}
        self._rebuild_title_index()
```

Add the TYPE_CHECKING import at the top of the file:
```python
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.cognitive.qualification import QualificationStore
```

### 2b: Add `set_qualification_store()` public setter

Add after `set_event_callback()`:

```python
    def set_qualification_store(self, store: Any) -> None:
        """AD-595d: Set qualification store for billet qualification checks."""
        self._qualification_store = store
```

### 2c: Add `check_qualifications()` async method

Add after `refresh()` (end of the read-side API, before `assign()`):

```python
    async def check_qualifications(
        self,
        billet_id: str,
        agent_type: str,
        agent_id: str = "",
        *,
        allow_untested: bool = True,
    ) -> tuple[bool, list[str]]:
        """AD-595d: Check if an agent meets a billet's qualification requirements.

        Parameters
        ----------
        billet_id : str
            Post identifier to check requirements for.
        agent_type : str
            Agent type — used to look up agent_id if not provided.
        agent_id : str
            Agent's sovereign/unique ID for qualification store lookup.
            If empty, looked up from current assignment.
        allow_untested : bool
            If True (default), agents with no test results for a required
            qualification are allowed through (cold-start tolerance).
            If False, missing test results count as failures (for promotion
            or re-qualification checks).

        Returns
        -------
        (qualified, missing) : tuple[bool, list[str]]
            True if all requirements met (or no requirements), plus list
            of missing/failed qualification test names.
        """
        post = self._dept.get_post(billet_id)
        if not post or not post.required_qualifications:
            return True, []

        if not self._qualification_store:
            # No store — can't check, allow by default
            return True, []

        # Resolve agent_id from assignment if not provided
        if not agent_id:
            assignment = self._dept.get_assignment_for_agent(agent_type)
            agent_id = assignment.agent_id if assignment and assignment.agent_id else ""

        if not agent_id:
            # Still no agent_id — can't look up results, allow by default
            return True, []

        missing: list[str] = []
        for test_name in post.required_qualifications:
            result = await self._qualification_store.get_latest(agent_id, test_name)
            if result is None:
                if not allow_untested:
                    missing.append(test_name)
                # else: cold start — no test taken yet, allow
            elif not result.passed:
                missing.append(test_name)

        return len(missing) == 0, missing
```

### 2d: Add `assign_qualified()` async method

Add after `check_qualifications()`:

```python
    async def assign_qualified(
        self,
        billet_id: str,
        agent_type: str,
        agent_id: str = "",
        callsign: str = "",
        *,
        allow_untested: bool = True,
    ) -> tuple[bool, list[str]]:
        """AD-595d: Check qualifications, then assign if qualified.

        Combines check_qualifications() + assign() in one call.
        If the agent doesn't meet requirements, the billet is NOT assigned.

        Parameters
        ----------
        billet_id, agent_type, agent_id, callsign :
            Same as assign() and check_qualifications().
        allow_untested : bool
            Passed through to check_qualifications(). Default True
            (cold-start tolerance).

        Returns
        -------
        (assigned, missing) : tuple[bool, list[str]]
            True if assigned, plus list of missing qualifications (empty
            if assigned, populated if rejected).
        """
        qualified, missing = await self.check_qualifications(
            billet_id, agent_type, agent_id, allow_untested=allow_untested,
        )
        if not qualified:
            logger.warning(
                "AD-595d: %s not qualified for billet %s — missing: %s",
                agent_type, billet_id, missing,
            )
            return False, missing

        result = self.assign(billet_id, agent_type, callsign=callsign)
        return result, []
```

**Do NOT modify `assign()`.** It stays sync, unconditional, no `force` parameter. `assign()` is a notification method — the gate lives on `assign_qualified()`.

---

## Section 3: Wire qualification store at startup

**File:** `src/probos/startup/finalize.py`

After the existing AD-595c wiring block, add:

```python
    # AD-595d: Wire QualificationStore into BilletRegistry
    billet_reg = runtime.ontology.billet_registry if runtime.ontology else None
    qual_store = getattr(runtime, '_qualification_store', None)
    if billet_reg and qual_store:
        billet_reg.set_qualification_store(qual_store)
        logger.info("AD-595d: Qualification store wired into BilletRegistry")
```

**Key points:**
- Access `billet_registry` through the public `runtime.ontology.billet_registry` path (same as AD-595c).
- Use `runtime._qualification_store` directly — this is the canonical attribute (see `runtime.py:430`). Do NOT reach through `_qualification_harness._store`.
- Use the `set_qualification_store()` public setter — do NOT write to `_qualification_store` directly from outside.

---

## Section 4: Tests

**File:** `tests/test_ad595d_qualification_gating.py` (NEW)

```python
"""Tests for AD-595d: Qualification-aware billet assignment."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

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
        post = Post(id="sensor_op", title="Sensor Operator", department_id="science", reports_to="chief_science_officer")
        assert post.required_qualifications == []


# --- Helper factories ---

def _make_mock_dept(posts: dict[str, Post] | None = None):
    """Create mock DepartmentService with given posts."""
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


def _make_mock_qual_store(results: dict[str, bool | None]):
    """Create mock QualificationStore.

    results: {test_name: passed_bool_or_None}.
    None means no test result exists (get_latest returns None).
    True/False means test exists with that passed value.
    """
    store = MagicMock()

    async def _get_latest(agent_id: str, test_name: str):
        if test_name not in results:
            return None
        val = results[test_name]
        if val is None:
            return None
        result = MagicMock()
        result.passed = val
        return result

    store.get_latest = AsyncMock(side_effect=_get_latest)
    return store


def _make_assignment(agent_id: str = "agent-001"):
    """Create a mock Assignment with agent_id."""
    assignment = MagicMock()
    assignment.agent_id = agent_id
    assignment.callsign = ""
    return assignment


# --- Qualification checking tests ---

class TestCheckQualifications:

    @pytest.mark.asyncio
    async def test_no_requirements_passes(self):
        """Agent qualifies for billet with no requirements."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(id="sensor_op", title="Sensor Op", department_id="science", reports_to=None)
        dept = _make_mock_dept({"sensor_op": post})
        store = _make_mock_qual_store({})

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
        dept = _make_mock_dept({"chief_engineer": post})
        store = _make_mock_qual_store({
            "bfi2_personality_probe": True,
            "episodic_recall_probe": True,
        })

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications("chief_engineer", "engineer", "agent-001")
        assert qualified
        assert missing == []

    @pytest.mark.asyncio
    async def test_missing_qualification_allow_untested(self):
        """Untested qualification allowed when allow_untested=True (cold start)."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe", "episodic_recall_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = _make_mock_qual_store({
            "bfi2_personality_probe": True,
            # episodic_recall_probe: no result exists
        })

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications(
            "chief_engineer", "engineer", "agent-001", allow_untested=True,
        )
        assert qualified
        assert missing == []

    @pytest.mark.asyncio
    async def test_missing_qualification_disallow_untested(self):
        """Untested qualification fails when allow_untested=False (promotion)."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe", "episodic_recall_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = _make_mock_qual_store({
            "bfi2_personality_probe": True,
            # episodic_recall_probe: no result exists
        })

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications(
            "chief_engineer", "engineer", "agent-001", allow_untested=False,
        )
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
        dept = _make_mock_dept({"chief_engineer": post})
        store = _make_mock_qual_store({"bfi2_personality_probe": False})

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
        dept = _make_mock_dept({"chief_engineer": post})

        reg = BilletRegistry(dept)  # No qualification_store
        qualified, missing = await reg.check_qualifications("chief_engineer", "engineer", "agent-001")
        assert qualified

    @pytest.mark.asyncio
    async def test_no_agent_id_passes_by_default(self):
        """Without agent_id and no assignment, qualification check passes."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = _make_mock_qual_store({})

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications("chief_engineer", "engineer", "")
        assert qualified

    @pytest.mark.asyncio
    async def test_agent_type_resolves_agent_id(self):
        """agent_type is used to look up agent_id when not provided."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        # Return an assignment so agent_id resolves
        dept.get_assignment_for_agent = MagicMock(return_value=_make_assignment("agent-001"))
        store = _make_mock_qual_store({"bfi2_personality_probe": True})

        reg = BilletRegistry(dept, qualification_store=store)
        # Pass empty agent_id — should resolve from assignment
        qualified, missing = await reg.check_qualifications("chief_engineer", "engineer", "")
        assert qualified
        store.get_latest.assert_called_once_with("agent-001", "bfi2_personality_probe")

    @pytest.mark.asyncio
    async def test_unknown_billet_passes(self):
        """Unknown billet returns qualified (nothing to check)."""
        from probos.ontology.billet_registry import BilletRegistry

        dept = _make_mock_dept({})
        store = _make_mock_qual_store({})

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications("unknown", "engineer", "agent-001")
        assert qualified

    @pytest.mark.asyncio
    async def test_cold_start_all_untested_passes(self):
        """Cold start: all qualifications untested, allow_untested=True → passes."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe", "episodic_recall_probe", "confab_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        # All return None — no tests taken yet
        store = _make_mock_qual_store({})

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications(
            "chief_engineer", "engineer", "agent-001", allow_untested=True,
        )
        assert qualified
        assert missing == []

    @pytest.mark.asyncio
    async def test_cold_start_all_untested_fails_strict(self):
        """Strict mode: all qualifications untested → fails."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe", "episodic_recall_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = _make_mock_qual_store({})

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications(
            "chief_engineer", "engineer", "agent-001", allow_untested=False,
        )
        assert not qualified
        assert len(missing) == 2


# --- assign_qualified tests ---

class TestAssignQualified:

    @pytest.mark.asyncio
    async def test_qualified_agent_assigned(self):
        """Qualified agent gets assigned via assign_qualified."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
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
        dept = _make_mock_dept({"chief_engineer": post})
        store = MagicMock()
        store.get_latest = AsyncMock(return_value=None)  # No test taken

        reg = BilletRegistry(dept, qualification_store=store)
        # allow_untested=False → strict mode → untested = missing
        assigned, missing = await reg.assign_qualified(
            "chief_engineer", "engineer", "agent-001", allow_untested=False,
        )
        assert not assigned
        assert "bfi2_personality_probe" in missing

    @pytest.mark.asyncio
    async def test_assign_unconditional(self):
        """assign() does not check qualifications — always assigns."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        # Even with qualifications required, assign() doesn't check
        reg = BilletRegistry(dept)  # No store at all
        result = reg.assign("chief_engineer", "engineer", callsign="LaForge")
        assert result

    @pytest.mark.asyncio
    async def test_assign_qualified_cold_start_allows_untested(self):
        """Cold start: assign_qualified with allow_untested=True succeeds."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = MagicMock()
        store.get_latest = AsyncMock(return_value=None)  # No test results

        reg = BilletRegistry(dept, qualification_store=store)
        assigned, missing = await reg.assign_qualified(
            "chief_engineer", "engineer", "agent-001",
            callsign="LaForge", allow_untested=True,  # default
        )
        assert assigned
        assert missing == []

    @pytest.mark.asyncio
    async def test_no_requirements_always_assigns(self):
        """Billet with no requirements always assigns via assign_qualified."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="sensor_op", title="Sensor Op",
            department_id="science", reports_to=None,
            # No required_qualifications
        )
        dept = _make_mock_dept({"sensor_op": post})
        store = _make_mock_qual_store({})

        reg = BilletRegistry(dept, qualification_store=store)
        assigned, missing = await reg.assign_qualified("sensor_op", "data_analyst", "agent-001")
        assert assigned
        assert missing == []


# --- set_qualification_store tests ---

class TestSetQualificationStore:

    def test_set_qualification_store(self):
        """set_qualification_store() sets the store."""
        from probos.ontology.billet_registry import BilletRegistry

        dept = _make_mock_dept({})
        reg = BilletRegistry(dept)
        assert reg._qualification_store is None

        store = MagicMock()
        reg.set_qualification_store(store)
        assert reg._qualification_store is store

    @pytest.mark.asyncio
    async def test_late_bound_store_works(self):
        """Store wired after construction works for qualification checks."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = _make_mock_qual_store({"bfi2_personality_probe": True})

        reg = BilletRegistry(dept)  # No store at construction
        # Check before store — should pass (no store = allow)
        q1, _ = await reg.check_qualifications("chief_engineer", "engineer", "agent-001")
        assert q1

        # Wire store
        reg.set_qualification_store(store)
        # Check after store — should pass (test passed)
        q2, _ = await reg.check_qualifications("chief_engineer", "engineer", "agent-001")
        assert q2
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

**Existing test impact:** Adding `required_qualifications` to `Post` uses `field(default_factory=list)`, so all existing `Post()` constructions remain valid. No changes to `assign()` signature — fully backwards compatible.

---

## Tracking

### PROGRESS.md
Add line:
```
AD-595d CLOSED. Qualification-aware billet assignment. Post gains required_qualifications field. BilletRegistry gains check_qualifications() async method with allow_untested cold-start tolerance, assign_qualified() async gated assignment, and set_qualification_store() public setter. assign() unchanged — stays sync and unconditional. Startup wiring connects QualificationStore → BilletRegistry via public setter. Data model + check API only — production gate deferred to AD-595e. 22 new tests. Depends on AD-595a + AD-539.
```

### DECISIONS.md
Add entry:
```markdown
### AD-595d — Qualification-Aware Billet Assignment

**Date:** 2026-04-24
**Status:** Complete
**Issue:** #TBD
**Parent:** AD-595 (Billet-Based Role Resolution)

**AD-595d: Data model + check API, no production gate.** Billets can declare `required_qualifications` (list of test names from AD-539). `check_qualifications()` async method verifies agent results from QualificationStore. `assign_qualified()` combines check + assign in one call. `allow_untested` parameter handles cold-start (no test results yet → allow) vs promotion (must have passed → block). `assign()` is NOT modified — stays sync and unconditional. Production assignment path (`agent_onboarding.py`) still calls `assign()`, unchanged. Gate enforcement deferred to AD-595e (promotion workflow). This split avoids the incoherent middle ground of logging-but-not-blocking and lets the data model ship immediately.
```

### docs/development/roadmap.md
Update AD-595d status from `planned` to `complete`. Add AD-595e:
```
> - **AD-595d: Qualification-Aware Assignment** *(complete, OSS, depends: AD-595a, AD-539)* — `Post` gains `required_qualifications` field. `BilletRegistry` gains `check_qualifications()` (async, with `allow_untested` cold-start tolerance) and `assign_qualified()`. Data model + check API only — `assign()` unchanged.
> - **AD-595e: Qualification Gate Enforcement** *(planned, OSS, depends: AD-595d)* — Wire `assign_qualified()` into promotion/assignment workflow. Production gate: Counselor/Captain approval checks qualifications before billet assignment. `allow_untested=False` for promotion, `True` for cold-start.
```
