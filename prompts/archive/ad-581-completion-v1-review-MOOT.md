# Review: AD-581-completion v1 — Finish AD-581a/b/d wiring
**Verdict:** ✅ Approved
**Closes 9 failing tests in `test_ad581_hybrid_dispatch.py` by adding 5 EventTypes, two order transitions, validators, and a finalize wirer.**

## Required (must fix before building)
_None._

## Recommended
1. **D2 defers `OrderStatus.PENDING` existence to Builder** ("Verify `OrderStatus` includes `PENDING`. Add it if missing"). Spec the exact addition: read `orders.py` once and either confirm or include the enum member in the prompt. This is a common Wave-128 false-positive hazard — Builder may infer the wrong default.
2. **D6 "Read `work_item_router.py` line 162 ± 30 lines to find the actual exception"** defers root-cause analysis to Builder. Architect should grep the line at draft time and tell the Builder *what* the bug is, not "find it." This converts a ~5-min architect read into a 30+ min Builder iteration.

## Nits
- D4 says `enabled: bool = True` "if not present" — phrase as a hard add to remove the conditional.
- The Acceptance line "no new test files" is correct but worth restating in the Tracking section for the Builder report template.

## Verified
- ✅ All 5 EventType strings, the 5 missing enum members, the SystemConfig wiring location, file paths, line numbers, the AD-581a/b/d pre-existing surface, the migration-by-test pattern.
- ✅ Tier-2 log-and-degrade for `_wire_hybrid_dispatch` matches the AD-673 anomaly-window precedent.
- ✅ Validators are Pydantic-v2 idiomatic.
- ✅ Scope is narrow (only files that need changing) and matches the test count (9 failing → 31/31 pass).

## Risk
LOW. Restoration BF on a substrate already shipped. Closes a known #504 with a precedent (`_wire_anomaly_window`).

## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved — phantom-class-name defect cleanly scrubbed; D2/D6 correctly demoted to verify-only.

### Required
None.

### Recommended
None.

### Nits
None.

### Verified
- `OrderStatus` → `OrderState` correction landed at all 4 sites (Verified-Against-Codebase line 16, Non-Goals line 46, Revision note line 104). The 4 grep hits remaining are intentional explanatory references — three explain that `OrderStatus` is **not** the canonical name; one is the revision-note paper trail. Zero normative directives use `OrderStatus`.
- D2 rewritten as verify-only: `decline()` (`:239`), `refuse()` (`:286`), and `Order.issue()` already exist with the correct emit machinery. **No code changes required in `orders.py`** — clearly stated.
- D6 rewritten as verify-only: traces the cascading `AttributeError` through `work_item_router.py:73` and `:117` to the missing EventType enum members. Concludes "**No code change is required in `work_item_router.py`**" — accurate.
- Acceptance criteria's `git diff` surface tightened to exactly `events.py`, `config.py`, `startup/finalize.py`.
- Phantom-API sweep: confirmed `OrderState` is the live class name (`cognitive/orders.py:28`).
