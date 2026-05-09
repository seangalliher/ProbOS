# Review: AD-707 — Workflow Cron Trigger
**Verdict:** ⚠️ Conditional
**Phantom API: `runtime.process_nl` does not exist. The prompt flags "verify-first: confirm method name" but still uses the wrong name in example code — Builder will copy-paste.**

## Required (must fix before building)
1. **Replace `runtime.process_nl` with `runtime.process_natural_language` throughout D3 and D1's `ProcessNLFn` docstring.** Grep evidence:
   ```
   grep -n "async def process_" src/probos/runtime.py
     2533: async def process_natural_language(
   ```
   No `process_nl` exists. The verify-first caveat in the prompt is correct in spirit but the literal example code at D3 (`process_nl_fn=runtime.process_nl,`) will mislead. Rewrite it.
2. **D1's `_load` uses `async with self._db.execute(...) as cursor: async for row in cursor`.** Confirm `DatabaseConnection` Protocol (per AD-664 ConnectionFactory) actually supports the async-iterator-cursor shape used here. If it only exposes `fetchall()` / `fetchone()`, the loop won't work. One-line spec addition: state which abstract method the loop relies on.

## Recommended
1. Add the working-tree integrity reminder (convention #20).
2. `_is_due` uses `croniter(expr, base).get_next(float)` — `get_next` returns the next-after-base time. With `base = last_fired_at` (or `created_at` for first eval) and a fast `tick_interval=1.0s`, a "every minute" trigger will fire every second once `now >= base + 60s` because the loop never advances `base`. The fix is in `_tick_once`: after firing, `last_fired_at = now` is set — but that handles only the post-fire case. Cold-start behavior at startup with `last_fired_at=0.0` falls back to `created_at` (correct per the hard-constraint note). Verify that the test `test_tick_does_not_fire_undue_trigger` actually catches the multi-second-window case.
3. `register` is `async` only because it touches the DB; consumers calling it under `await` is fine, but the in-memory dict assignment isn't lock-protected. Consider `async with self._lock` inside `register` / `cancel` if concurrent registration is expected. (AD-707c may add this; flag for now.)
4. Line drift: `workflow_cache.py:33 def store` actual is `:29`; `:55 def lookup` actual is `:56`. Tighten or use "around line N".

## Nits
- `pyproject.toml:37` for `croniter>=1.3` is a useful citation but quick double-check the version matches what's pinned today.
- `WorkflowCronTrigger` is mutable (`@dataclass`, not frozen). Justifiable since `last_fired_at` and `fire_count` mutate, but mark as such — design note welcome.

## Verified
- `src/probos/cognitive/workflow_cache.py:17` `class WorkflowCache` — confirmed.
- `src/probos/cognitive/workflow_cache.py:29` `def store(self, user_input: str, dag: TaskDAG)` — confirmed (prompt says `:33`, drift = 4).
- `src/probos/cognitive/workflow_cache.py:150` `_normalize` — confirmed.
- `src/probos/types.py:599` `class WorkflowCacheEntry` — confirmed shape (pattern, dag_json, hit_count, last_hit, created_at).
- `src/probos/runtime.py:406` `self.workflow_cache = WorkflowCache()` — confirmed.
- `enabled: bool = False` default — convention #14 honored.
- `croniter` already declared (no new dependency).
- Hard-constraint list correctly defers webhook / REST API / direct cache-lookup / subprocess scheduling.

## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved
**Both pass-1 Required items landed inline; build-ordering note added.**

### Required
None.

### Recommended
None new.

### Nits
None new.

### Verified Improvements (pass-2)
- ✅ **Required #1 (process_nl phantom):** Select-String -Path prompts/ad-707-workflow-cron-trigger-v1.md -Pattern "process_natural_language" returns 6 hits in normative content (lines 19, 20, 50, 94, 103, 283). Residual process_nl hits (2) are confined to (a) the Verified-Against-Codebase note explicitly documenting 	here is no process_nl method and (b) the Revision Notes — both non-normative.
- ✅ **Required #2 (DB-protocol pre-check note):** Verified inline in _load body at lines 184–197 (`Builder pre-check (Required #2): confirm the AD-664 `DatabaseConnection` Protocol exposes the async-cursor / async-iterator shape`). Includes the etchall() fallback shape — Builder has both options.
- ✅ Build Ordering Note present (config.py serialization slot: claude-bootstrap → AD-701 → AD-707 → Memvid-QP).
- ✅ Working-tree integrity reminder in Acceptance section.
- ✅ `WorkflowCache.store/lookup/_normalize` verified at HEAD (workflow_cache.py:29, 56, 150).
- ✅ `runtime.process_natural_language` verified at HEAD (untime.py:2533).

### Pass-2 outcome
Promoted from ⚠️ to ✅. Cleared for Builder dispatch.
