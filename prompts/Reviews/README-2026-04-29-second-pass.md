# Prompt Review — Second Pass (2026-04-29)

**Reviewer:** Architect
**Scope:** Re-review of the 4 prompts from the 2026-04-29 first-pass sweep, after author
revisions.
**Prior pass:** [README.md](README.md) (first pass, same date)

---

## Verdict Summary

| Verdict | First Pass | Second Pass |
|---|---|---|
| ✅ Approved | 1 | **3** |
| ⚠️ Conditional | 1 | 0 |
| ❌ Not Ready | 2 | **1** |
| 📦 Archived | 0 | **1** |

---

## Per-Prompt Verdicts

| Prompt | First Pass | Second Pass | Resolution |
|---|---|---|---|
| AD-680 | ❌ Not Ready | ❌ Not Ready | Unchanged. Three of five "private attrs" still don't exist; `runtime.emit_event` is already public. Needs rescope. |
| BF-246 | ⚠️ Conditional | ✅ Approved | All 5 Required items resolved; emit_fn now used; init moved to `__init__`; uses public `runtime.emit_event`; first-probe delay test added; config validator added. |
| BF-247 | ✅ Approved | ✅ Approved | Rescoped after production fix landed (commit `8be47d5`). Prompt now covers test-only follow-up. Cleaner shape. |
| BF-248 | ❌ Not Ready (Stale) | 📦 Archived | Moved to `prompts/archive/bf-248-anomaly-window-llm-event-field.md`. Resolved per Option 1 of first-pass disposition. |

Per-prompt detail (with appended "Re-review" sections):

- [ad-680-expose-runtime-public-properties-review.md](ad-680-expose-runtime-public-properties-review.md)
- [bf-246-llm-tier-recovery-deadlock-review.md](bf-246-llm-tier-recovery-deadlock-review.md)
- [bf-247-tiered-knowledge-dag-summary-type-review.md](bf-247-tiered-knowledge-dag-summary-type-review.md)
- [bf-248-anomaly-window-llm-event-field-review.md](bf-248-anomaly-window-llm-event-field-review.md)

---

## What Changed Since First Pass

### BF-246 (revised, now approved)

The author folded essentially every Required and Recommended item from the first review:

- Instance attributes initialized in `__init__` (Step 1a) — eliminates the
  defensive-`getattr` anti-pattern.
- `emit_fn` is now actually called in the loop transition branch with a try/except
  guard. Adds `"source": "bf246_probe"` to the payload for telemetry.
- Section 3 wires through public `runtime.emit_event` (verified at `runtime.py:771`
  and `protocols.py:105`) rather than `_emit_event`.
- New "Why This Works" section explains the line-379 fallback-skip interaction and
  the deliberate first-probe delay.
- Field validator on `health_probe_interval_seconds` rejects values < 5.0.
- New tests 8 (first-probe-delayed) and 9 (validator rejection).
- New "Verified Against Codebase" section pastes grep evidence for every claim.

This is the verify-first discipline working as intended.

### BF-247 (rescoped after production fix)

The production fix (Sections 1-3 of the original prompt) landed in commit `8be47d5`.
The prompt was rescoped to a test-only follow-up — 4 tests covering the fixed paths.
This is the right move; shipping the test additions in a separate commit is fine as
long as PROGRESS.md tracks BF-247 as "Open (tests pending)" until the tests land.

### BF-248 (archived)

Moved to `prompts/archive/`. Resolution matches Option 1 of the first-pass review.
A small DECISIONS.md entry capturing the AD-673 spec defect (which BF-248 was meant to
fix, but had already been patched out-of-band) would be worth one line — it documents
the process gap that produced the stale prompt in the first place.

### AD-680 (unchanged)

No revisions since first pass. The original review's findings stand:

- `_trust_network`, `_router`, `_add_event_listener_fn` — none exist as private
  attributes. Public surface (`trust_network`, `hebbian_router`, `add_event_listener`)
  already in use throughout `startup/finalize.py`.
- `# TODO(AD-571)` and `# TODO(AD-673)` markers — zero matches in `src/`.
- **New observation this pass:** `runtime.emit_event` already exists as a public
  method at `runtime.py:771` (delegates to `_emit_event`). This was confirmed while
  verifying BF-246's Section 3. Net effect: the ~20-call-site `_emit_event` migration
  workstream in AD-680 is reducible to a one-line search-and-replace today, with no
  runtime change required.

The honest scope of AD-680 is now:

| Work | Sites | Notes |
|---|---|---|
| `runtime._emit_event` → `runtime.emit_event` | ~20 | Pure call-site migration; `runtime.emit_event` already exists. |
| `_emergence_metrics_engine` → public property | 1 | `startup/finalize.py:160`. Trivial. |
| Drop `trust_network` / `router` / `add_event_listener_fn` workstreams | 0 | These attributes don't exist. |

That's two PRs of ~30 minutes each. Not five-properties-and-six-tests as the prompt
currently describes. Recommend rewriting AD-680 around the actual scope, or splitting
into AD-680a (call-site migration) and AD-680b (`_emergence_metrics_engine`).

---

## Cross-Cutting Patterns

### 1. Verify-first discipline produced a fast, clean turnaround on BF-246

The first-pass review listed five Required items, each tied to specific lines and grep
evidence. The author addressed all five and added a "Verified Against Codebase" section
of their own. The second pass is mostly a confirmation that the fixes match the
findings. This is the workflow working.

### 2. Out-of-band fixes need an audit trail

BF-247's production fix landed without a DECISIONS.md or AD entry, just a commit hash.
BF-248's fix did the same earlier. Neither is wrong, but both make follow-up reviews
harder because the live state diverges from the prompt history. Recommend a one-line
DECISIONS.md entry whenever a prompt's spec is patched mid-flight or a fix lands ahead
of its prompt — even just `[date] BF-XXX section N landed early in commit <hash>; see
prompt for context`.

### 3. Stale prompts should self-archive

BF-248's archive resolution worked. Consider adding a `pre-commit` or CI check that
runs each active prompt's SEARCH blocks against the live files and flags any that no
longer match. This would catch stale prompts before a reviewer wastes time on them.

### 4. AD-680 needs author engagement

Without revisions, AD-680 stays blocked. A 15-minute rewrite (drop the three phantom
attributes, frame around the two real targets, and ship) would make this trivially
approvable. The prompt's good intent — clean up private-attr access in wiring code —
is correct; only the scope claims are wrong.

---

## Build Order

**Wave A — ship now:**

- **BF-246** — Approved this pass. Builder can start.
- **BF-247** — Approved (test-only follow-up). Builder can start. Coordinate with
  PROGRESS.md status to reflect "tests pending" until they land.

**Wave B — needs author rework:**

- **AD-680** — Rewrite around the two real targets, then re-review. Should not block
  BF-246/BF-247.

**Wave C — done:**

- **BF-248** — Archived. No further action.
