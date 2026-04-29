# Prompt Review — Third Pass (2026-04-29)

**Reviewer:** Architect
**Scope:** Re-review after AD-680 rewrite. BF-246 and BF-247 unchanged since second pass.
**Prior passes:**
- [README.md](README.md) (first pass, 2026-04-29)
- [README-2026-04-29-second-pass.md](README-2026-04-29-second-pass.md) (second pass)

---

## Verdict Summary

| Verdict | First | Second | Third |
|---|---|---|---|
| ✅ Approved | 1 | 3 | **3** |
| ⚠️ Conditional | 1 | 0 | 0 |
| ❌ Not Ready | 2 | 1 | **0** |
| 📦 Archived | 0 | 1 | 1 |

**All active prompts approved. Clean sweep.**

---

## Per-Prompt Verdicts

| Prompt | Second | Third | Notes |
|---|---|---|---|
| AD-680 | ❌ Not Ready | ✅ **Approved** | Fully rewritten around the two real targets (`_emit_event`, `_emergence_metrics_engine`). Phantom workstreams removed. |
| BF-246 | ✅ Approved | ✅ Approved | Unchanged since second pass. |
| BF-247 | ✅ Approved | ✅ Approved | Unchanged since second pass. |
| BF-248 | 📦 Archived | 📦 Archived | Stays archived. |

Per-prompt detail (with appended Re-review sections):

- [ad-680-expose-runtime-public-properties-review.md](ad-680-expose-runtime-public-properties-review.md)
- [bf-246-llm-tier-recovery-deadlock-review.md](bf-246-llm-tier-recovery-deadlock-review.md)
- [bf-247-tiered-knowledge-dag-summary-type-review.md](bf-247-tiered-knowledge-dag-summary-type-review.md)

---

## What Changed Since Second Pass

### AD-680 (rewritten)

Title changed from "Expose Runtime Public Properties" to "Promote `_emit_event` and
`_emergence_metrics_engine` to Public API." The new prompt:

- Drops the three phantom workstreams (`trust_network`, `router`, `add_event_listener`)
  — those attributes are already public.
- Frames the work around two concrete migrations: a type-hint widening on the
  already-existing `runtime.emit_event` method, and a new `emergence_metrics_engine`
  property.
- Section 3 lists 8 files for the `_emit_event` call-site migration with approximate
  counts and explicit grep instructions ("run grep to confirm — do not rely on this
  list alone"). Good posture — counts will drift.
- Section 3 includes a "Do NOT touch" subsection that correctly excludes
  `self._emit_event` on `TrustNetwork`, `CognitiveQueue`, `WardRoomService` and
  similar — those are local callback attributes that happen to share the name. This
  was the highest-risk Builder mistake the original prompt could have produced.
- Test 4 is a regression guard: scans `src/probos/` (excluding `runtime.py`) for the
  three call-site shapes and asserts zero matches.
- "Verified Against Codebase" section pastes grep evidence for every claim.

Verified by my own grep:
- 8 external `_emergence_metrics_engine` sites in exactly the 4 files listed ✓
- `runtime.emit_event` at `runtime.py:771` ✓
- `RuntimeProtocol.emit_event` at `protocols.py:105` ✓
- All three call-site shapes (`runtime._emit_event`, `rt._emit_event`,
  `self._runtime._emit_event`) present in the codebase ✓

---

## Cross-Cutting Patterns

### 1. The verify-first standing order kept this batch tight

All three approved prompts now carry a "Verified Against Codebase" section with grep
evidence. AD-680's iteration history is the strongest case: first-pass review found
five fabricated APIs; second-pass found `runtime.emit_event` already public; third-pass
shows the rewritten prompt checks every claim before asserting it. Recommend treating
"Verified Against Codebase" as a mandatory section in the prompt template.

### 2. The "Do NOT touch" subsection in AD-680 is a model worth copying

Bulk migrations across grep matches are dangerous when the same name appears on
unrelated classes. AD-680 Section 3 spells out the disambiguation rule explicitly
(*"If the line has `self._emit_event` where `self` is NOT `ProbOSRuntime`, leave
it"*). This is the kind of guard that prevents a one-character regex from rewriting
half the codebase. Future bulk-migration prompts should include the same
disambiguation discipline.

### 3. Iteration count for this batch: 3 passes for AD-680, 2 for BF-246, 1 for BF-247/248

Pattern matches the user-memory note ("Three-pass prompt review converges fast when
the author is responsive"). All three live prompts are now ready in under a day of
review work.

---

## Build Order

**Wave A — ship now (parallel safe):**

- **BF-247** — Test-only follow-up. Smallest risk. Builder can start immediately.
- **BF-246** — Independent feature. Builder can start in parallel.

**Wave B — ship after Wave A passes its tests:**

- **AD-680** — Largest blast radius (~8 files). Doing it last lets the BF-246/247
  test gate catch any regressions that come from the call-site migration.

**Wave C — done:**

- **BF-248** — Archived. No action.

---

## Notes for the Author

- AD-680's nits in the third-pass review (lambda-wrapper edge case, signature
  introspection in Test 1) are non-blocking. Builder can handle them at code-review
  time.
- One-line `DECISIONS.md` entry for AD-680 worth recording: precedent for "no
  deprecation warning, one-shot migration" of private→public promotions.
