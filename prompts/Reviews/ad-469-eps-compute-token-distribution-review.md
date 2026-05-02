# Review: AD-469 — EPS Compute/Token Distribution (v1)

**Verdict:** ❌ Not Ready — phantom `tokens_grouped_by` API in shipping content. Real method is `get_token_usage_by`. Mechanical fix; no architectural rework, but Required for correctness. One Recommended in Section 4 (`check_budgets()` returning `[]`).

**Date:** 2026-05-02

**Headline:** Section 2's `CapacityTracker.summary()` calls `journal.tokens_grouped_by(group_by=...)` which does not exist. The real method is `get_token_usage_by(group_by=...)`. The verify-first footer hallucinates the wrong line.

---

## Required (must fix before building)

1. **Phantom API — `journal.tokens_grouped_by` does not exist.** Section 2 `capacity.py` lines 152-154:

   ```python
   by_agent = await journal.tokens_grouped_by(group_by="agent_id")
   by_tier = await journal.tokens_grouped_by(group_by="tier")
   by_model = await journal.tokens_grouped_by(group_by="model")
   ```

   Live source at `src/probos/cognitive/journal.py:299-301`:

   ```python
   async def get_token_usage_by(
       self, group_by: str = "model", agent_id: str | None = None,
   ) -> list[dict[str, Any]]:
   ```

   The method name is `get_token_usage_by`, NOT `tokens_grouped_by`. **Fix:** rewrite all three calls to use `get_token_usage_by(group_by=...)`. Builder will get an `AttributeError` on first run otherwise.

2. **Phantom verify-first footer line.** The footer claims:

   ```
   grep -n "async def tokens_grouped_by\|async def get_agent_tokens_since" src/probos/cognitive/journal.py
     278: async def get_agent_tokens_since(  # AD-617b
     300: async def tokens_grouped_by(
   ```

   Line 300 is `async def get_token_usage_by(` not `async def tokens_grouped_by`. The grep result is hallucinated. **Fix:** correct the footer to match the live method name.

3. **Wrong dict-key reads on `get_token_usage_by` rows.** Live `get_token_usage_by` returns rows keyed:

   ```python
   {
       group_by: row["group_key"],     # the group key dynamically named
       "total_calls": row["calls"] or 0,
       "total_tokens": row["tokens"] or 0,
       "prompt_tokens": ...,
       "completion_tokens": ...,
       "avg_latency_ms": ...,
   }
   ```

   Section 2 reads `row.get("calls", 0)`:

   ```python
   total_calls = sum(int(row.get("calls", 0) or 0) for row in by_agent)
   ```

   The real key is `"total_calls"` (note: live source returns `"total_calls"` from line 334). `row.get("calls", 0)` will always return `0` — `total_calls` and `calls_per_minute` will silently report zero forever. **Fix:** rewrite to `row.get("total_calls", 0)`. Same for `total_tokens` reads (line 162-163: `row.get("total_tokens", 0)` — that key IS correct per the live API; ✅ that one's fine).

4. **Wrong dict-key reads for the group key.** Section 2 lines 173-178:

   ```python
   by_agent={
       str(row.get("agent_id", "") or ""): int(row.get("total_tokens", 0) or 0)
       for row in by_agent
   },
   by_tier={
       str(row.get("tier", "") or ""): int(row.get("total_tokens", 0) or 0)
       for row in by_tier
   },
   by_model={
       str(row.get("model", "") or ""): int(row.get("total_tokens", 0) or 0)
       for row in by_model
   },
   ```

   Live source at line 333: `{group_by: row["group_key"], ...}`. So when called with `group_by="agent_id"`, the result row has key `"agent_id"` — and `row.get("agent_id", "")` works. Same for `"tier"` and `"model"`. **This actually works** but is fragile (the dict-key access depends on the `group_by` argument value matching exactly). Mark as ⚠️ pass — but the fragility deserves a comment.

   Also: the `total_tokens` key at line 174/179/183 IS `"total_tokens"` per live source line 335. ✅. (My initial read was wrong on this one.)

   Net: only Required #3's `"calls"` -> `"total_calls"` is a true bug; the group-key path is correct but fragile.

---

## Recommended

1. **`check_budgets()` returns `[]` always — convention #7 borderline.** Section 4 `EPSCoordinator.check_budgets` is documented as v1-empty-list per the prompt's own no-theater note. The method exists, declares its v1 contract, and reserves `EPS_BUDGET_EXCEEDED` for AD-469b. This is honest deferral, but the method itself is dead code in v1. Consider:

   - (a) Drop the method from v1 entirely; rely on AD-469b's prompt to introduce it.
   - (b) Keep it but add a `NotImplementedError` raise so callers are loud about unintended use.
   - (c) Keep current behavior; document the v1 contract more explicitly in the docstring.

   Recommend (a). Empty-list-by-design has a Pavlovian risk: callers may write code assuming "no offenders" instead of "feature unwired."

2. **`since` variable in `summary()` is unused.** Line 150:

   ```python
   since = time.time() - self._window_seconds
   ```

   `since` is never passed to `get_token_usage_by` (which doesn't support a `since` param anyway in v1). Drop the unused variable, OR document that windowed filtering is an AD-469b extension.

3. **`CapacitySummary.tokens_per_minute` calculation assumes window-aligned data.** The aggregate is across ALL journal entries (no time filter), divided by `window_seconds * 60`. If the journal is 14 days deep (the AD-431 retention default), `tokens_per_minute` overstates current rate by a factor of `14*24*60 / 60 = ~336`. Recommend adding a `since=` param to `get_token_usage_by` (a small extension, but it's an API change to AD-460 which the dispatch warned against), OR filtering the rows post-hoc by joining on the journal's `timestamp` column. This is the actual capacity-tracking quality issue, not just a comment problem.

4. **Section 7 finalize wiring uses `CapacityTracker(runtime=runtime, window_seconds=...)` keyword-only.** Section 2's `CapacityTracker.__init__` is `def __init__(self, *, runtime: Any, window_seconds: float = ...)`. ✅ matches.

5. **`DepartmentBudgetTable.allocations()` proportional renormalization** is correct mathematically. But the renormalization fires regardless of whether the configured percents originally summed to 1.0. If percents sum to 0.95 and engineering is overridden to 0.50, remaining 5 departments share 0.50 / 0.95 of their original percent — slightly different from "share 0.50 directly." Behavior is reasonable; document it.

6. **Test #7 default-allocations sum-to-one** assumes the default config sums to exactly 1.0. Default percents in the EPSConfig: 0.30 + 0.20 + 0.15 + 0.15 + 0.10 + 0.10 = 1.00. ✅ exact.

---

## Nits

- `CapacityTracker` docstring claims "Stateless. Each call queries the journal afresh; no caching." ✅
- `EPSReport.capacity: Any` typing — to avoid circular import. The dataclass typing comment justifies this. ✅
- Section 0 EventTypes `EPS_BUDGET_EXCEEDED` and `EPS_REALLOCATION` are free in `events.py`. ✅
- Section 6 `EPSConfig` 6 default departments + percents sum to 1.0 — clean. ✅
- Section 5 anchor uses post-AD-463 line 211 — correct, no Wave 8 dependency. ✅
- Convention #11 `getattr(self, "_runtime", None)` defensive read in `summary()` — applied. ✅
- The "v1 ships 3 of 7 capabilities" framing matches the body. No Solution-Overview drift. ✅

---

## Verified (looks good)

- `runtime.cognitive_journal: CognitiveJournal | None = None` at `runtime.py:213, 424, 1593`. ✅
- `runtime.llm_client: BaseLLMClient` at `runtime.py:347`. ✅
- `runtime.emit_event` at `runtime.py:785`. ✅
- `class IntentBus` at `mesh/intent.py:NN`. ✅
- `runtime.eps_coordinator` is a NEW public attribute per Wave 5 convention #1.
- 4 of 7 capabilities (alert-aware reallocation, back-pressure, atomic enforcement, prompt caching) wholesale-deferred at draft time per convention #14. ✅
- `model_routing: ModelRoutingConfig` anchor at `config.py:1693` for Section 6. ✅
- No `CognitiveJournal` schema changes. ✅ (per dispatch verification point #2)

---

## Conventions audit

| # | Rule | Status |
|---|---|---|
| 1 | Public-attribute wiring | ✅ |
| 2 | stdlib-only | ✅ |
| 3 | Coordinator-then-dispatch | ✅ |
| 4 | Superset-filter | ✅ read-only over journal |
| 5 | init_<phase> | ✅ |
| 6 | Verify-first | ❌ Required #1 + #2 (phantom API + hallucinated grep result) |
| 7 | No-theater | ⚠️ Recommended #1 (`check_budgets` returns `[]` always) |
| 8 | TYPE_CHECKING + ALLOWED_EXCEPTIONS | N/A |
| 9 | ASCII-only comments | ✅ |
| 10 | work_item_store vs workforce | N/A |
| 11 | __new__-bypass defensive-getattr | ✅ |
| 12 | Solution Overview drift | ✅ |
| 13 | Pool template name collision | N/A |
| 14 | Aggressive pre-deferral | ✅ 4 of 7 |
| 15 | Tolerance: relaxed | n/a (review tier) |

---

## Bottom Line

The phantom-`tokens_grouped_by` issue is exactly the failure shape Wave 5-7 retrospective addendum #6 ("phantom APIs in defensive-read paths") warned about, and the dispatch's pre-check guidance was supposed to prevent. Mechanical fix: replace `tokens_grouped_by` with `get_token_usage_by` and `row.get("calls", ...)` with `row.get("total_calls", ...)`. After revision, this prompt should converge cleanly. **Verdict will flip to ✅ Approved on second-pass review when the phantom is gone.**

The Required is mechanical, not architectural — but it's a "would not work on first run" bug, not a polish item. Hence ❌ Not Ready.
