# Review: BF-248 — Anomaly Window Reads Wrong Event Field for LLM Status

**Reviewer:** Architect
**Date:** 2026-04-29
**Verdict:** ❌ **Not Ready (Stale)** — The bug has already been fixed in the live code.
The prompt's SEARCH blocks will not match. Disposition options below.

**Re-review (2026-04-29, second pass): ✅ Resolved by archive.** The prompt was moved
to `prompts/archive/bf-248-anomaly-window-llm-event-field.md`, matching this review's
recommended Option 1.

---

## Summary

The diagnosis was correct at the time it was written, but **the fix has already landed**
in both `src/probos/startup/finalize.py` and `tests/test_ad673_anomaly_window.py`.
The prompt's SEARCH blocks describe code that no longer exists. Building this prompt as
written will fail at the first SEARCH/REPLACE because the search strings don't match the
current file.

---

## Evidence the bug is already fixed

### Production code (`src/probos/startup/finalize.py`, current contents around line 57)

```python
elif event_type_value == EventType.LLM_HEALTH_CHANGED.value:
    status = ""
    if isinstance(data, dict):
        status = data.get("new_status") or data.get("status", "")
    if status in ("degraded", "offline"):
        manager.open_window("llm_degraded", f"LLM status: {status}")
    elif status in ("operational", "healthy") and manager.is_active():
        active_window = manager.get_active_window()
        if active_window:
            manager.close_window(active_window)
```

The current code already:

- Reads `data.get("new_status")` first (the correct field).
- Falls back to `data.get("status")` for backward compatibility.
- Accepts both `"operational"` and `"healthy"` as the recovered state.

### Test code (`tests/test_ad673_anomaly_window.py:189-190`)

```python
await listener(LlmHealthChangedEvent(old_status="operational", new_status="degraded").to_dict())
await listener(LlmHealthChangedEvent(old_status="degraded", new_status="operational").to_dict())
```

The tests construct real `LlmHealthChangedEvent` instances and call `.to_dict()` — the
exact pattern the prompt asks for.

---

## Required (if the prompt is to be salvaged rather than archived)

### 1. SEARCH blocks do not match — the prompt cannot run as-is

Both SEARCH strings in Sections 1 and 2 will fail string-match against the current code.
The builder will halt at the first replacement.

**Action:** Either archive the prompt (see "Recommended Disposition" below) or rewrite
the SEARCH blocks to match the current file contents.

### 2. The proposed REPLACE introduces a regression

The current code accepts the legacy `data.get("status")` field as a fallback. The prompt's
REPLACE removes that fallback. If any in-flight event payloads still use the flat
`{"status": ...}` shape (e.g., from `_health_probe_emit` in BF-246, which proposes
emitting `{"new_status": ..., "old_status": ...}` — but if a future emitter drops the
prefix, this breaks silently), they would stop opening anomaly windows.

**Action:** Either keep the legacy fallback for one release cycle and document a planned
removal AD, or grep all emitters first and confirm none use the flat shape.

Grep confirms: `LlmHealthChangedEvent.to_dict()` is the only emitter, and it uses
`new_status` / `old_status`. So removing the fallback is safe — but the prompt should
state this explicitly.

### 3. The proposed REPLACE removes the `"healthy"` accept-state

Current code accepts `("operational", "healthy")`. Proposed REPLACE accepts only
`"operational"`. The codebase comment on `events.py:608-609` says the only real values
are `"operational", "degraded", "offline", "recovering"` — `"healthy"` was never produced
by `LlmHealthChangedEvent`, so removing it is technically safe but undocumented.

**Action:** Add a one-line note to the prompt: "Drop `'healthy'` because
`LlmHealthChangedEvent.to_dict()` never emits it; the only producer of that string was
the broken legacy code path."

### 4. Test SEARCH blocks also do not match

The current test code uses `LlmHealthChangedEvent(...).to_dict()` constructors, not raw
dicts. The prompt's SEARCH (`{"data": {"status": "degraded"}}`) does not exist in the
file. The "fix" the prompt describes is already in place.

---

## Recommended

### R1. Reframe as a cleanup AD, not a bug fix

If the goal is to remove the legacy `data.get("status")` fallback and the `"healthy"`
accept-state, write a small cleanup AD:

> **AD-XXX (or BF-248 reframed):** Drop legacy LLM health event field fallback.
> The `LlmHealthChangedEvent` schema has stabilized on `new_status`/`old_status`.
> Remove the `or data.get("status", "")` fallback and the `"healthy"` legacy accept-state.
> One file changed, three lines removed, no behavioral change in production.

### R2. Capture the lesson in DECISIONS.md

The original AD-673 prompt asserted a wrong event schema. The Architect approved it
without verifying. The fix landed in a follow-up commit that is not yet recorded as an
AD or BF. Add a `DECISIONS.md` entry summarizing:

- AD-673 spec asserted `data.get("status")`. Wrong. Real schema is `new_status`/`old_status`.
- Mid-flight fix added the dual-key read.
- BF-248 prompt was authored to do the fix that had already landed.

This is the kind of process drift worth capturing so the next reviewer audits the live
state before drafting a "fix" prompt.

---

## Nits

- The "Why Tests Don't Catch It" framing in BF-247 was a useful diagnostic pattern.
  BF-248 would benefit from the same framing — the new question is "Why did the
  out-of-band fix land without an AD/BF marker?"
- `data.get("new_status", "")` already returns `""` on a None data dict — the
  `if isinstance(data, dict)` guard in the current code is belt-and-suspenders. Fine to
  keep, but worth documenting *why* (some emitters historically pass non-dict payloads).

---

## Verified

- `events.py:605-612` — `LlmHealthChangedEvent` defines `old_status` / `new_status`
  fields. ✓
- `tests/test_ad673_anomaly_window.py:176, 189, 190` — tests already use
  `LlmHealthChangedEvent(...).to_dict()`. ✓
- `finalize.py:58-66` — code already reads `new_status` first with `status` fallback
  and accepts both `operational` and `healthy`. ✓
- The bug as originally described was real, just already fixed.

---

## Recommended Disposition

**Choose one:**

1. **Archive as already-resolved.** Move the prompt to `prompts/archive/` with a brief
   note explaining that the fix landed out-of-band. Add a DECISIONS.md entry capturing
   the process gap (AD-673 spec defect, no recording of the live fix).

2. **Rewrite as a cleanup AD.** Drop the legacy `or data.get("status", "")` fallback and
   the `"healthy"` accept-state. Three lines removed, one targeted test added. Easier
   review. New name: BF-248 → AD-681 (Cleanup) or keep the BF number with a
   "completes the partial fix" framing.

Option 1 is cleaner. Option 2 is ~15 minutes of builder time and removes dead code.
Either is fine; what's not fine is shipping the prompt as-is.
