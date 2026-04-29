# Prompt Review Sweep — 2026-04-29

**Reviewer:** Architect
**Scope:** All 4 active prompts in `prompts/` (top level)
**Prior sweep:** `Reviews/archive/README-2026-04-27.md` (re-review #3, 20 prompts approved)

---

## Verdict Summary

| Verdict | Count |
|---|---|
| ✅ Approved | **1** |
| ⚠️ Conditional | **1** |
| ❌ Not Ready | **2** |

---

## Per-Prompt Verdicts

| Prompt | Title | Verdict | Headline |
|---|---|---|---|
| AD-680 | Expose Runtime Public Properties | ❌ Not Ready | Three of five "private attrs" are already public; TODO markers don't exist; rework required |
| BF-246 | LLM Tier Recovery Deadlock | ⚠️ Conditional | Real bug, sound design; one bug in proposed code + several spec gaps |
| BF-247 | TieredKnowledgeLoader dag_summary Type | ✅ Approved | Clean fix, all references verified, two minor quality nits |
| BF-248 | Anomaly Window Wrong Event Field | ❌ Not Ready (Stale) | Bug already fixed in production; SEARCH blocks won't match |

Per-prompt detail in:

- [ad-680-expose-runtime-public-properties-review.md](ad-680-expose-runtime-public-properties-review.md)
- [bf-246-llm-tier-recovery-deadlock-review.md](bf-246-llm-tier-recovery-deadlock-review.md)
- [bf-247-tiered-knowledge-dag-summary-type-review.md](bf-247-tiered-knowledge-dag-summary-type-review.md)
- [bf-248-anomaly-window-llm-event-field-review.md](bf-248-anomaly-window-llm-event-field-review.md)

---

## Cross-Cutting Patterns Observed

### 1. Verify-first discipline broke down for two of four prompts

**AD-680** asserts the existence of five private attributes and `# TODO(AD-571)` /
`# TODO(AD-673)` markers. Workspace grep shows:

- `runtime._trust_network` — does not exist (already public as `runtime.trust_network`).
- `runtime._router` — does not exist (already public as `runtime.hebbian_router`).
- `runtime._add_event_listener_fn` — does not exist (already public as `runtime.add_event_listener`).
- `# TODO(AD-571)` — zero matches in `src/`.
- `# TODO(AD-673)` — zero matches in `src/`.

**BF-248** describes a bug in `finalize.py:58` and proposes SEARCH/REPLACE blocks. The
described buggy code does not exist in the current file — it was fixed out-of-band in a
prior commit with no AD/BF record. The prompt cannot run.

Both failures stem from the same root cause: the prompts were drafted from
prior-state memory rather than against the live codebase. This is exactly the
verify-first lesson from the user-memory file (`probos-architect-learnings.md`) and the
copilot-instructions standing order on Build Prompt Verification.

**Standing recommendation:** every prompt should include a "Verified against codebase"
section near the top with grep evidence (paths + line numbers) for every concrete API,
attribute, line number, and code fragment it references. The verification step is
cheap; the cost of skipping it is two prompts that would have wasted Builder cycles.

### 2. Defensive `getattr` for in-prompt APIs is creeping back in

BF-246's `start_health_probe` initializes `self._health_probe_task` inside the start
method, then `stop_health_probe` and `close()` use `getattr(self, "_health_probe_task", None)`
fallbacks. This is the exact anti-pattern flagged in the user-memory:
> "Defensive `getattr(obj, 'method', None)` for APIs defined in the same prompt."

Fix at the source: initialize state in `__init__`, then references can be direct.

### 3. Out-of-band fixes without an AD/BF record

BF-248 reveals that AD-673's incorrect event-schema assertion was fixed without recording
the change. The fix is good; the lack of a record meant a follow-up reviewer drafted a
duplicate prompt. Recommend a one-line DECISIONS.md entry every time a prompt's spec is
patched mid-flight.

### 4. Stale prompts still on disk

BF-248 describes a bug that no longer exists. Recommend a periodic sweep that diffs each
active prompt's SEARCH blocks against the live files and archives any that no longer
apply.

---

## Recommended Build Order

**Wave A — ship now:**

- **BF-247** — Approved, low-risk, isolated fix. ~4 tests, two files.

**Wave B — ship after one round of revisions:**

- **BF-246** — Conditional. Address Required items 1-5 (init bug, unused emit_fn,
  AD-680 dependency, shutdown spec gap, config location) and ship.

**Wave C — block on rework:**

- **AD-680** — Rescope to the two real targets (`_emit_event`, `_emergence_metrics_engine`)
  and re-author. Even better, **rename** `_emit_event` → `emit_event` instead of
  exposing it via a property. Drop the trust_network / router / add_event_listener
  workstreams entirely (the public surface already exists).

**Wave D — disposition decision needed:**

- **BF-248** — Either archive as already-resolved (cleaner) or rewrite as a small
  cleanup AD that drops the dual-key fallback and the `"healthy"` legacy accept-state.

---

## Notes

- `Reviews/archive/` preserves the prior 20-prompt sweep and per-prompt review files.
- All four current per-prompt review files are in `Reviews/<stem>-review.md` form.
- AD-680 is structurally interesting because it sits at the boundary between "public API
  hygiene" and "rename refactor." If the chosen path is the rename (recommended), the AD
  should be reframed accordingly and a precedent recorded in DECISIONS.md.
- BF-247's pattern (legacy `isinstance(x, str)` guard for type-evolved fields) is worth
  documenting as a standard idiom — episode-shape evolution will keep happening, and a
  consistent guard pattern reduces future bug surface.
