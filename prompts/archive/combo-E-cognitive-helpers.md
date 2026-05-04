# Combo E v1: AD-508 (Scoped Cognition — Duty Scope) + AD-478 (Meta-Learning — Workspace Ontology)

**Status:** Drafted (Wave 23)
**Risk:** low (read-only observational helpers)
**Closes:** GitHub issues #90 (AD-508), #72 (AD-478)

---

## Combo Rationale

Both are 4-capability ADs with deep deps (AD-507 / AD-273 etc.) but each has a single bounded v1 capability with clean shipping surface. Combining as Combo E ships 2 issues in 1 commit; both observational read-only consumers; no infrastructure asks.

**v1 ships 1 of 4 per child:**

- **AD-508 v1 — Duty Scope helper.** Read-only `DutyScopeProvider.snapshot(agent_id)` returning `DutyScopeSnapshot(agent_id, active_work_items, current_intent)` from `runtime.work_item_store.list_work_items(assigned_to=agent_id, status="open")`. Caller-driven; not yet injected into proactive context (that's AD-508b). Just exposes the data surface.
- **AD-478 v1 — Workspace Ontology read-only register.** `WorkspaceOntologyRegistry.add_term(term, frequency)` + `top_terms(k)` — bounded in-memory ring (default 1000 terms) tracking conceptual vocabulary frequency from usage. NO auto-discovery in v1; callers register terms manually. Auto-discovery from dream cycle output is AD-478b.

**Deferred:**
- AD-508b/c/d/e: Role/Ship/Personal scope, scope injection into proactive context, drift detection, Earned Agency scaling.
- AD-478b/c/d: Auto-discovery from dream cycles, persistent goals, abstract pattern recognition.

## Section 0 — EventTypes

- `DUTY_SCOPE_QUERIED` — emitted on snapshot.
- `WORKSPACE_TERM_REGISTERED` — emitted on term add (frequency-bounded; only emit on add, not every increment).

## Section 1 — Files

- `src/probos/cognitive/scoped_cognition.py` (NEW; ~80 lines). Contains `DutyScopeSnapshot` + `DutyScopeProvider`.
- `src/probos/cognitive/workspace_ontology.py` (NEW; ~80 lines). Contains `WorkspaceOntologyRegistry`.

## Section 2 — DutyScopeProvider (AD-508 v1)

```python
@dataclass(frozen=True)
class DutyScopeSnapshot:
    """Per-agent duty scope view. AD-508 v1."""
    agent_id: str
    open_work_item_count: int
    work_item_titles: tuple[str, ...]  # up to 5 most recent titles
    captured_at: float


class DutyScopeProvider:
    """v1 observational read-only Duty Scope helper. AD-508 v1.

    Future consumer (AD-508b): proactive cognitive loop injects DutyScopeSnapshot
    into context["duty_scope"]. v1 just exposes the surface.
    """

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self.emit_event: Callable[..., None] | None = None

    async def snapshot(self, agent_id: str) -> DutyScopeSnapshot:
        """Return DutyScopeSnapshot for agent. Empty when work_item_store missing."""
        if not agent_id:
            return DutyScopeSnapshot(agent_id="", open_work_item_count=0, work_item_titles=(), captured_at=time.time())
        store = getattr(self._runtime, "work_item_store", None)
        titles: tuple[str, ...] = ()
        count = 0
        if store is not None:
            try:
                items = await store.list_work_items(status="open", assigned_to=agent_id, limit=5)
                count = len(items)
                titles = tuple(getattr(it, "title", "") or "" for it in items[:5])
            except Exception:
                logger.debug("AD-508: list_work_items failed", exc_info=True)
        snap = DutyScopeSnapshot(
            agent_id=agent_id,
            open_work_item_count=count,
            work_item_titles=titles,
            captured_at=time.time(),
        )
        self._emit(snap)
        return snap

    def _emit(self, snap: DutyScopeSnapshot) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.DUTY_SCOPE_QUERIED,
                {"agent_id": snap.agent_id, "open_count": snap.open_work_item_count},
            )
        except Exception:
            logger.warning("AD-508: emit_event failed", exc_info=True)
```

## Section 3 — WorkspaceOntologyRegistry (AD-478 v1)

```python
class WorkspaceOntologyRegistry:
    """v1 in-memory frequency-bounded term registry. AD-478 v1.

    Future consumer (AD-478b): dream cycle auto-discovers terms. v1 callers
    register manually.
    """

    def __init__(self, max_terms: int = 1000) -> None:
        self._max_terms = max_terms
        self._terms: dict[str, int] = {}  # term -> frequency
        self.emit_event: Callable[..., None] | None = None

    def add_term(self, term: str, frequency: int = 1) -> None:
        """Register/increment term frequency. Evicts lowest-freq when at cap."""
        if not term:
            return
        is_new = term not in self._terms
        self._terms[term] = self._terms.get(term, 0) + frequency
        if len(self._terms) > self._max_terms:
            # Evict lowest-frequency term
            evict = min(self._terms.items(), key=lambda kv: kv[1])[0]
            del self._terms[evict]
        if is_new:
            self._emit(term, self._terms[term])

    def top_terms(self, k: int = 20) -> tuple[tuple[str, int], ...]:
        """Top k terms by frequency, descending."""
        if k <= 0:
            return ()
        sorted_terms = sorted(self._terms.items(), key=lambda kv: kv[1], reverse=True)
        return tuple(sorted_terms[:k])

    def get_frequency(self, term: str) -> int:
        return self._terms.get(term, 0)

    def term_count(self) -> int:
        return len(self._terms)

    def _emit(self, term: str, frequency: int) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.WORKSPACE_TERM_REGISTERED,
                {"term_length": len(term), "frequency": frequency},  # privacy: term length, not term itself
            )
        except Exception:
            logger.warning("AD-478: emit_event failed", exc_info=True)
```

**Privacy:** event payload includes `term_length` (NOT term itself). Even though terms aren't sensitive in principle, applying the privacy invariant pattern from AD-530/AD-511.

## Section 4 — Pydantic config + Section 5 — Wiring

```python
class ScopedCognitionConfig(BaseModel):
    """AD-508 v1."""
    enabled: bool = True


class WorkspaceOntologyConfig(BaseModel):
    """AD-478 v1."""
    enabled: bool = True
    max_terms: int = 1000
```

`SystemConfig.scoped_cognition` + `SystemConfig.workspace_ontology`.

Sync `_wire_duty_scope_provider` + `_wire_workspace_ontology` mirror AD-525/AD-530 pattern. Public attrs: `runtime.duty_scope_provider`, `runtime.workspace_ontology`.

## What Combo E Does NOT Change

- AD-508b/c/d/e — all deferred (Role/Ship/Personal scope, proactive context injection, drift detection, Earned Agency).
- AD-478b/c/d — all deferred (auto-discovery, persistent goals, abstract pattern recognition).
- proactive cognitive loop — untouched. v1 surfaces the data; consumers come later.
- KnowledgeStore — not consumed by v1; AD-478b handles persistence.
- Dream cycle — not consumed by v1; AD-478b handles auto-discovery.

## Test Plan (~16 tests)

AD-508 (~8):
1. `test_duty_scope_snapshot_is_frozen_dataclass`
2. `test_snapshot_empty_agent_id_returns_empty`
3. `test_snapshot_no_work_item_store_returns_empty`
4. `test_snapshot_calls_list_work_items_with_open_status_assigned_to`
5. `test_snapshot_extracts_titles_up_to_5`
6. `test_snapshot_emits_duty_scope_queried_event`
7. `test_runtime_attribute_set_when_enabled`
8. `test_runtime_attribute_not_set_when_disabled`

AD-478 (~8):
1. `test_workspace_ontology_registry_initial_state`
2. `test_add_term_increments_frequency`
3. `test_add_term_empty_string_no_op`
4. `test_top_terms_returns_descending_order`
5. `test_top_terms_respects_k_limit`
6. `test_max_terms_eviction_drops_lowest_frequency`
7. `test_add_term_emits_event_only_on_new_term` (privacy: term_length not term)
8. `test_runtime_attribute_set_when_enabled`

## Tracking

PROGRESS.md / DECISIONS.md (Era V combined) / roadmap.md (flip AD-508 + AD-478 to partial).

GH issues to close: #90, #72.

## Verified Against Codebase (2026-05-03)

```
grep -n "list_work_items" src/probos/workforce.py
  1066: async def list_work_items(self, status, assigned_to, work_type, parent_id, priority, tags, limit, offset)

grep -n "_wire_classification_gate\|_wire_creative_expression" src/probos/startup/finalize.py
  (Builder verifies sibling _wire_<feature> sync def pattern)

grep -rn "duty_scope_provider\|workspace_ontology" src/probos/
  (Expected: 0 hits — verifies attribute names are free)
```

## Acceptance Criteria

- 2 new files (scoped_cognition.py + workspace_ontology.py).
- 2 new EventTypes (DUTY_SCOPE_QUERIED, WORKSPACE_TERM_REGISTERED).
- 2 new public attrs (no underscore).
- 2 new Pydantic configs wired into SystemConfig.
- ~16 tests pass.
- Single commit `Combo E: AD-508 + AD-478 observational v1 (cognitive helpers; b/c/d/e + b/c/d deferred)`.
- DECISIONS.md combined entry under Era V.
- 2 roadmap.md status flags flipped.
- GH #90 + #72 BOTH closed.

## Hard-Stops

- v1 scope creep on either child.
- Privacy regression (term contents in events).
- Pre-check finds new phantoms beyond documented FPs.
