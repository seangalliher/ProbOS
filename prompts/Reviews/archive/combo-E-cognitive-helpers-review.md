# Review: Combo E — AD-508 + AD-478 (cognitive helpers v1)

**Verdict:** ✅ Approved
**Two read-only observational helpers, pre-deferral discipline clean, privacy invariant honored, no phantoms.**

Pass-1 (2026-05-04, single-pass per Wave 23 dispatch). Convention #15 tolerance relaxed (1 ⚠️ allowed); this review surfaces 0 Required + 1 Recommended + 4 Nits, well within budget.

## Required (must fix before building)

_None._

## Recommended

1. **Section 5 wiring spec is gestural** — "mirror AD-525/AD-530 pattern" is the entire wiring contract for both helpers. Sibling patterns diverge: `_wire_creative_expression` (finalize.py:80-103) uses a private `_emit_event_fn` attribute set after construction; `_wire_classification_gate` (finalize.py:105-118) uses an `emit_event=emit_fn` constructor kwarg. Section 2 of the prompt declares `self.emit_event: Callable[..., None] | None = None` as a public mutable field set externally (Captain-style late-bind). All three shapes are valid, but the Builder should pick one explicitly. Recommend the AD-530 ctor-injection shape for both new helpers (`DutyScopeProvider(runtime, emit_event=emit_fn)`, `WorkspaceOntologyRegistry(max_terms=cfg.max_terms, emit_event=emit_fn)`) — fewest moving parts, matches the most recent sibling, and avoids the public-mutable-`emit_event` naming collision with `runtime.emit_event` itself. If the Builder prefers the late-bind public-field shape (as Section 2 currently shows), that is acceptable too — but pick one and stay consistent across both files. Not blocking; pick during implementation.

## Nits

1. **Implicit imports.** Section 2/3 use `time.time()`, `Callable`, `logger`, `EventType` without showing the import block. All routine; Builder will add them. Mention here for completeness.
2. **Eviction tie-break is implementation-defined but deterministic.** `min(self._terms.items(), key=lambda kv: kv[1])` returns the first insertion-order entry on ties (CPython 3.7+ dict ordering). Acceptable for a v1 frequency-bounded ring. Could note in docstring that "ties evict oldest insertion." Optional.
3. **`DutyScopeSnapshot.work_item_titles` truncation.** Section 2 caps at 5 in two places (`limit=5` on the store call AND `[:5]` on the slice). Belt-and-suspenders is fine; Builder should keep both in case `WorkItemStore` ignores `limit`.
4. **`top_terms(k=0)` returns `()`.** Section 3 short-circuits negative/zero k. Good. Test `test_top_terms_respects_k_limit` should also exercise `k=0` boundary explicitly.

## Verified

- **Pre-deferral honesty (point 1).** Combo Rationale states "v1 ships 1 of 4 per child" explicitly. AD-508b/c/d/e and AD-478b/c/d each enumerated under "Deferred". "What Combo E Does NOT Change" repeats the deferred surface (proactive context injection, dream-cycle auto-discovery, KnowledgeStore consumption). Pre-deferral pattern matches Combo D / Wave 19 discipline.
- **`WorkItemStore.list_work_items` kwargs (point 2).** Verified at `src/probos/workforce.py:1066-1077`. Real signature: `(self, status, assigned_to, work_type, parent_id, priority, tags, limit, offset)`. Section 2 calls `await store.list_work_items(status="open", assigned_to=agent_id, limit=5)` — all three kwargs exist, kwargs-only invocation, no positional-arg drift risk.
- **Privacy invariant on `WORKSPACE_TERM_REGISTERED` (point 3).** Section 3 emits payload `{"term_length": len(term), "frequency": frequency}` with explicit comment "privacy: term length, not term itself". Mirrors the AD-530 `content_length`-only / AD-511 `blocked_phrases`-by-name invariant. No regression vector.
- **Eviction logic on `max_terms` cap (point 4).** `if len(self._terms) > self._max_terms: evict = min(self._terms.items(), key=lambda kv: kv[1])[0]; del self._terms[evict]`. Drops lowest-frequency. Test #6 (`test_max_terms_eviction_drops_lowest_frequency`) covers it. Edge case (ties) is deterministic via insertion order; acceptable for v1.
- **AD-685 + AD-685b coverage (point 5).** Phantom-API pre-check expectation: `runtime.duty_scope_provider` and `runtime.workspace_ontology` should produce 0 hits in `src/probos/` (verified — both introduced). The only external method dependency is `runtime.work_item_store.list_work_items(...)` — real, verified at workforce.py:1066. No method-name phantoms.
- **Sibling wiring exists.** `_wire_creative_expression` and `_wire_classification_gate` both real at `src/probos/startup/finalize.py:80,105`; new `_wire_duty_scope_provider` + `_wire_workspace_ontology` follow established convention.
- **EventType slot.** `DUTY_SCOPE_QUERIED` and `WORKSPACE_TERM_REGISTERED` are new enum values introduced by Section 0; not flagged as missing per verify-first migration rule.
- **Pydantic config.** `ScopedCognitionConfig` + `WorkspaceOntologyConfig` both have sensible defaults (`enabled=True`, `max_terms=1000`); ProbOS still boots zero-config.
- **"What This Does NOT Change" enumerated.** Proactive cognitive loop, KnowledgeStore, dream cycle all explicitly listed as untouched.
- **GH issue closure.** #90 (AD-508) + #72 (AD-478) tracked.

## Hard-Stops

1. **v1 scope creep on either child.** ✅ Clear. Both children explicitly bounded to 1 of 4 capabilities; deferred surface enumerated.
2. **Privacy regression (term contents in events).** ✅ Clear. `term_length` only; no term string in payload.
3. **Pre-check finds new phantoms beyond documented FPs.** ✅ Clear. Documented FPs (`runtime.duty_scope_provider`, `runtime.workspace_ontology`) confirmed as introduced attrs (0 grep hits in src/). Only external dep is `WorkItemStore.list_work_items` — real signature verified.

## Convention Tolerance

Wave 23 dispatch relaxes Wave 5 convention #15 to allow 1 ⚠️ Conditional. This review is ✅ Approved (0 Req); tolerance unused.

---

**Builder green-light: proceed to implementation, single commit, push.**
