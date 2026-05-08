# Review: AD-700b v1 — Cognitive Journal level tagging for `diagnose_system`
**Verdict:** ✅ Approved
**Two-column additive migration with gated population. Sound shape; one Recommended sharpening to confirm the `_decide_via_llm` integration site.**

## Required (must fix before building)
_None._

## Recommended
1. **D4 cites `cognitive_agent.py:1660–1740` as "the journal-record block — verified at HEAD (kwargs match `record()` signature)" — but does not show the existing `await journal.record(...)` call site.** A 4-line snippet of the existing call (file + line + the 3 lines around it + the existing kwargs) lets the Builder match indentation, kwarg ordering, and any wrapping `try/except`. Without the snippet, the gating insertion (`if observation.get("intent") == "diagnose_system":`) may end up in the wrong block — and a journal `record()` call that crashes silently fails the AD-700b telemetry without breaking any test.

## Nits
1. D2's `_migrate_ad700b()` mirrors `_migrate_ad664()` — good. Confirm whether `_migrate_ad664` is wired into `start()` between `_SCHEMA_BASE` (line 197) and `_SCHEMA_INDEXES` (line 211); if not, the BF-031 ordering claim should be revised. (The prompt asserts the ordering is canonical — verify against `journal.py:start()` once at draft time.)
2. Test #4's "pre-create a journal DB with the AD-431/432 schema only" requires the Builder to know the AD-431/432 baseline schema. Reference an existing fixture or a one-line SQL snippet; otherwise the Builder will either guess or skip the legacy path.
3. The new index `idx_journal_level` is on a column with default `''` — most rows will share the empty key. Consider a partial index `WHERE level != ''` to avoid index bloat. (Optional — performance is not a v1 concern.)

## Verified
- ✅ `_SCHEMA_BASE` at `journal.py:21`, `_SCHEMA_INDEXES` at `:51`, `start()` at `:186`, `record()` at `:328`. All grep-confirmed.
- ✅ Schema column types/defaults follow SQLite best-practice (`TEXT NOT NULL DEFAULT ''`, `INTEGER NOT NULL DEFAULT 0`).
- ✅ `record()` is kwarg-only with explicit defaults — appending two new kwargs is forward-compatible.
- ✅ Gating logic ("populate only when `intent == 'diagnose_system'`") preserves journal readability for non-diagnostic rows.
- ✅ DiagnosticianAgent's `perceive()` already populates `result["level"]` and `result["level_rank"]` — no agent change required.
- ✅ Six tests cover the boundary surface (write+read both columns, non-diagnostic empty, all 5 levels round-trip, migration on legacy DB, idempotent migration, index existence).

## Risk
LOW-MEDIUM. Schema migration is the highest-risk surface but the additive-column pattern + idempotent guard limits blast radius. Existing journal tests in `test_cognitive_journal.py` provide regression coverage.

## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved — line range corrected to 1722-1748; insertion point unambiguous.

### Required / Recommended / Nits
None.

### Verified
- **Recommended #1 landed**: Exact `await self._cognitive_journal.record(...)` block inlined in Verified-Against-Codebase at `cognitive_agent.py:1722-1748`. Verified at HEAD: lines 1721-1750 match the inlined snippet exactly (`if self._cognitive_journal:` guard, `try:` block, `record()` kwargs in documented order, `except Exception: logger.debug(...)`).
- D1 schema additions place after `correlation_id` (last current column). D2 migration mirrors BF-031 ordering.
- D4 inline ternary gates on `observation.get("intent") == "diagnose_system"` at kwarg level — explicit.
- 6 tests cover happy path, non-diagnose default, L1-L5 round-trip, migration, idempotency, index existence.
- No drift on AD-700c boundary: short-circuit `return` skips this block, consistent with both prompts.
- Phantom-API sweep: clean.
