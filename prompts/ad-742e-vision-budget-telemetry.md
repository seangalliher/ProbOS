# AD-742e — Vision LLM call budget telemetry in HXI status badge

**Status:** Drafted Wave 174. Closes #673.
**Dependencies:** AD-733a (VisionConsumer), AD-742a (vision_fast tier — for per-tier counter). Strict build order: AD-742a → AD-742b → AD-742e (telemetry sees both surfaces complete).
**Estimated:** ~3 hours, single commit, +6 pytest, +6 vitest.
**Risk:** LOW — additive UI component + one new API endpoint reading server counters. No tier wiring, no new pip/npm deps.

---

## Problem

The AD-733a v1 enforces `vision_min_interval_seconds=3.0s` (cost-discipline floor) and a session-wide ceiling (`proactive_max_emissions=3` for the proactive observer). Today the Captain has no real-time view of how close to the budget the session is — they review journal traces after the fact. Surface running totals in the HXI status badge: `· Vis 12/120` with hover for breakdown. AD-742a's `vision_fast` tier is cheaper than `vision`; separate counters give cost discipline visibility.

## Solution

`VisionConsumer` maintains in-memory per-tier counters: `vision`, `vision_fast`. Per-session totals reset on session change. Per-day totals reset on date rollover (UTC). A new endpoint `GET /api/perception/budget` returns the structured counter shape. A new `<VisionBudgetBadge />` component in HXI polls the endpoint every 5 s and renders `· Vis N/M` when `N > 0`, hidden when `N == 0`. Hover-title shows the breakdown.

**v1 in-memory only.** Forward marker AD-742e-1 for SQLite persistence (`vision_call_log` table) post-build.

---

## Section 1: VisionConsumer counters

Edit `src/probos/perception/consumer.py`. Insert counter state in `__init__`:

```
===SEARCH===
        self._identity_resolved_sessions: set[str] = set()
        # AD-742b: lazy-constructed face-embedding resolver. Threaded
        # through __init__ rather than constructed here so tests can
        # inject a stub.
        self._identity_resolver: Any = None
===REPLACE===
        self._identity_resolved_sessions: set[str] = set()
        # AD-742b: lazy-constructed face-embedding resolver. Threaded
        # through __init__ rather than constructed here so tests can
        # inject a stub.
        self._identity_resolver: Any = None

        # AD-742e (Wave 174): per-tier vision LLM call counters. Reset
        # per-session on session change; per-day on UTC date rollover.
        # v1 in-memory only — AD-742e-1 forward marker for SQLite
        # persistence across restart.
        self._budget_calls_session: dict[str, int] = {"vision": 0, "vision_fast": 0}
        self._budget_calls_today: dict[str, int] = {"vision": 0, "vision_fast": 0}
        self._budget_current_session_id: str = ""
        self._budget_current_date: str = ""  # YYYY-MM-DD UTC
        self._budget_last_call_at: float | None = None
===END REPLACE===
```

(Anchor depends on AD-742b being merged first. If AD-742b is not yet shipped at build time, use this alternate anchor:

```
===SEARCH===
        self._identity_resolved_sessions: set[str] = set()
===REPLACE===
        self._identity_resolved_sessions: set[str] = set()

        # AD-742e (Wave 174): per-tier vision LLM call counters. Reset
        # per-session on session change; per-day on UTC date rollover.
        # v1 in-memory only — AD-742e-1 forward marker for SQLite
        # persistence across restart.
        self._budget_calls_session: dict[str, int] = {"vision": 0, "vision_fast": 0}
        self._budget_calls_today: dict[str, int] = {"vision": 0, "vision_fast": 0}
        self._budget_current_session_id: str = ""
        self._budget_current_date: str = ""  # YYYY-MM-DD UTC
        self._budget_last_call_at: float | None = None
===END REPLACE===
```

Builder MUST pick the variant matching the current HEAD state.)

Add helper methods (insert after `set_identity_resolver` if AD-742b shipped first, else after `subscribe`):

```python
    def _record_vision_call(self, tier: str, session_id: str) -> None:
        """AD-742e: record one vision LLM call against the budget counters."""
        import time as _time
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if session_id != self._budget_current_session_id:
            self._budget_current_session_id = session_id
            self._budget_calls_session = {"vision": 0, "vision_fast": 0}
        if today != self._budget_current_date:
            self._budget_current_date = today
            self._budget_calls_today = {"vision": 0, "vision_fast": 0}
        if tier not in self._budget_calls_session:
            self._budget_calls_session[tier] = 0
            self._budget_calls_today[tier] = 0
        self._budget_calls_session[tier] += 1
        self._budget_calls_today[tier] += 1
        self._budget_last_call_at = _time.monotonic()

    def get_budget_snapshot(self) -> dict[str, Any]:
        """AD-742e: structured snapshot for /api/perception/budget."""
        import time as _time
        next_allowed_in: float = 0.0
        if self._budget_last_call_at is not None:
            elapsed = _time.monotonic() - self._budget_last_call_at
            next_allowed_in = max(0.0, self._min_interval - elapsed)
        ceiling = 0
        # session ceiling = proactive_max_emissions + a per-frame describe
        # estimate (min_interval = 3s -> ~20/min -> ~120 in a typical 5-min
        # session). v1 uses the proactive ceiling * 40 heuristic since the
        # actual ceiling is a function of session duration which isn't known.
        cfg = getattr(self._runtime.config, "perception", None)
        if cfg is not None:
            ceiling = int(getattr(cfg, "proactive_max_emissions", 3)) * 40
        return {
            "session_id": self._budget_current_session_id,
            "calls_this_session": dict(self._budget_calls_session),
            "calls_today": dict(self._budget_calls_today),
            "total_session": sum(self._budget_calls_session.values()),
            "total_today": sum(self._budget_calls_today.values()),
            "session_ceiling_estimate": ceiling,
            "next_allowed_in_seconds": round(next_allowed_in, 2),
        }
```

Then increment the counter in `_describe` immediately after the `llm_client.complete` call succeeds (the `response.content` extraction is the success boundary). Builder MUST grep `_describe` and find the spot AFTER the `response = await asyncio.wait_for(...)` line, BEFORE `return (response.content or "").strip()`. The recorded `tier` is the `describe_tier` variable from AD-742a.

```
===SEARCH===
            response = await asyncio.wait_for(
                self._runtime.llm_client.complete(request),
                timeout=self._timeout,
            )
            return (response.content or "").strip()
        except Exception:
            logger.warning(
                "AD-733a: vision LLM describe failed for sha=%s",
                sha[:8], exc_info=True,
            )
            return ""
===REPLACE===
            response = await asyncio.wait_for(
                self._runtime.llm_client.complete(request),
                timeout=self._timeout,
            )
            # AD-742e: record successful call against the budget counter.
            # `describe_tier` is the resolved tier (vision_fast when configured,
            # else vision) from the AD-742a routing block above.
            self._record_vision_call(describe_tier, self._budget_current_session_id or "default")
            return (response.content or "").strip()
        except Exception:
            logger.warning(
                "AD-733a: vision LLM describe failed for sha=%s",
                sha[:8], exc_info=True,
            )
            return ""
===END REPLACE===
```

(Builder note: AD-742a introduces `describe_tier`. If AD-742a Section 5 hasn't shipped at build time, replace `describe_tier` with `self._tier` and a forward-marker comment to fix at AD-742a merge.)

Also set `self._budget_current_session_id` in `_process` when the session changes. Find the existing `session_id = str(msg.params.get("session_id", ""))` at consumer.py:197 — no edit needed; the `_record_vision_call` reset logic handles session change. But for `force_describe_current_frame` (consumer.py:318), the session_id must be threaded through. Builder MUST grep `force_describe_current_frame` and confirm `session_id` is in scope at the LLM-call site; if it is, the AD-742a-installed `describe_tier` logic already covers it via the same `_describe` helper.

---

## Section 2: API endpoint

Edit `src/probos/routers/perception.py`. Add a new GET endpoint after the existing `@router.get("/recent")` block (line 174):

```python
@router.get("/budget", dependencies=[Depends(require_crew_scope)])
async def get_vision_budget(
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-742e (Wave 174): vision LLM call budget telemetry.

    Returns per-tier (vision / vision_fast) call counts for the current
    session AND for today (UTC). Plus a next-allowed-in estimate based
    on the supervisor's min-interval floor.
    """
    consumer = getattr(runtime, "vision_consumer", None)
    if consumer is None:
        return {
            "session_id": "",
            "calls_this_session": {"vision": 0, "vision_fast": 0},
            "calls_today": {"vision": 0, "vision_fast": 0},
            "total_session": 0,
            "total_today": 0,
            "session_ceiling_estimate": 0,
            "next_allowed_in_seconds": 0.0,
            "consumer_wired": False,
        }
    snapshot = consumer.get_budget_snapshot()
    snapshot["consumer_wired"] = True
    return snapshot
```

(Builder MUST verify `Depends` + `require_crew_scope` + `get_runtime` are already imported — they are per the existing `/recent`, `/mode`, `/engage` endpoints. No new imports required.)

---

## Section 3: HXI `<VisionBudgetBadge />` component

Create `ui/src/components/perception/VisionBudgetBadge.tsx`:

```tsx
import React, { useEffect, useState } from 'react';

interface BudgetSnapshot {
  session_id: string;
  calls_this_session: Record<string, number>;
  calls_today: Record<string, number>;
  total_session: number;
  total_today: number;
  session_ceiling_estimate: number;
  next_allowed_in_seconds: number;
  consumer_wired: boolean;
}

const POLL_INTERVAL_MS = 5000;

export function VisionBudgetBadge() {
  const [snapshot, setSnapshot] = useState<BudgetSnapshot | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const resp = await fetch('/api/perception/budget', { credentials: 'same-origin' });
        if (!resp.ok) return;
        const data: BudgetSnapshot = await resp.json();
        if (!cancelled) setSnapshot(data);
      } catch {
        // tier-2 log-and-degrade: silent. Badge just stays hidden.
      }
    }
    poll();
    const id = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // HXI Principle #5: progressive disclosure. Hidden when no calls yet.
  if (!snapshot || snapshot.total_session === 0) {
    return null;
  }

  const { total_session, session_ceiling_estimate, calls_this_session, calls_today, next_allowed_in_seconds } = snapshot;
  const ceiling = session_ceiling_estimate > 0 ? session_ceiling_estimate : 120;
  const pct = total_session / ceiling;
  const color = pct >= 1.0 ? '#c84858' : pct >= 0.8 ? '#d49050' : '#f0b060';

  const titleParts = [
    `vision: ${calls_this_session.vision || 0}`,
    `vision_fast: ${calls_this_session.vision_fast || 0}`,
    `today: ${(calls_today.vision || 0) + (calls_today.vision_fast || 0)}`,
    next_allowed_in_seconds > 0 ? `next in ${next_allowed_in_seconds.toFixed(1)}s` : 'ready',
  ];

  return (
    <span
      style={{ display: 'flex', gap: 4, alignItems: 'center' }}
      title={titleParts.join(' · ')}
      data-testid="vision-budget-badge"
    >
      <span style={{ color: '#666680' }}>Vis</span>
      <span style={{ color }}>{total_session}/{ceiling}</span>
    </span>
  );
}
```

Mount it in `ui/src/components/DecisionSurface.tsx` immediately after the Entropy span. Builder MUST find the exact anchor:

```
===SEARCH===
        {/* Routing Entropy */}
        <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}
              title="Routing Entropy \u2014 diversity of intent routing paths">
          <span style={{ color: '#666680' }}>Entropy</span>
          <span style={{ color: '#88a4c8' }}>{routingEntropy.toFixed(3)}</span>
        </span>

        {/* Spacer */}
===REPLACE===
        {/* Routing Entropy */}
        <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}
              title="Routing Entropy \u2014 diversity of intent routing paths">
          <span style={{ color: '#666680' }}>Entropy</span>
          <span style={{ color: '#88a4c8' }}>{routingEntropy.toFixed(3)}</span>
        </span>

        {/* AD-742e: Vision budget badge (hidden when total_session == 0) */}
        <VisionBudgetBadge />

        {/* Spacer */}
===END REPLACE===
```

And add the import (Builder MUST grep `import` lines at top of DecisionSurface.tsx):

```
===SEARCH===
import { Sparkle, StatusPending, StatusDone } from './icons/Glyphs';
===REPLACE===
import { Sparkle, StatusPending, StatusDone } from './icons/Glyphs';
import { VisionBudgetBadge } from './perception/VisionBudgetBadge';
===END REPLACE===
```

---

## Tests

### Pytest (+6)

`tests/test_ad742e_vision_budget.py`:

1. `test_consumer_starts_with_zero_counters` — fresh `VisionConsumer` has `calls_this_session == {"vision": 0, "vision_fast": 0}`.
2. `test_record_vision_call_increments_session_and_today` — call `_record_vision_call("vision", "sess1")` twice; both counters at 2.
3. `test_record_vision_call_resets_on_session_change` — record 2 under "sess1"; record 1 under "sess2"; session counter is 1, today counter is 3.
4. `test_record_vision_call_resets_on_date_rollover` — monkey-patch `datetime.now` to return two dates; verify today counter resets.
5. `test_get_budget_snapshot_shape` — record some calls; snapshot returns all required keys with right types.
6. `test_api_endpoint_returns_snapshot` — using the existing FastAPI test client pattern from `tests/test_routers_perception.py` (or equivalent); GET `/api/perception/budget` returns 200 with the snapshot shape. When `runtime.vision_consumer is None`, returns `consumer_wired: False`.

### Vitest (+6)

`ui/src/components/perception/__tests__/VisionBudgetBadge.test.tsx`:

1. `renders nothing when fetch returns total_session=0` — mock fetch returning `total_session: 0`; component renders null.
2. `renders badge when total_session > 0` — mock fetch returning `total_session: 12, session_ceiling_estimate: 120`; component renders `12/120`.
3. `renders amber when below 80% ceiling` — mock 10/120; color style is `#f0b060`.
4. `renders dim red when 80-100%` — mock 100/120; color style is `#d49050`.
5. `renders bright red when at ceiling` — mock 120/120; color style is `#c84858`.
6. `hover-title shows per-tier breakdown` — mock with vision=8, vision_fast=4; check `title` attr contains both `vision: 8` and `vision_fast: 4`.

---

## What this does NOT change

- AD-733a min-interval enforcement (this AD just *reports* the budget; it doesn't change throttling).
- AD-733b proactive observer ceiling (still hard-bounded at `proactive_max_emissions=3`).
- AD-732 / AD-742a tier routing.
- IntentBus shape.
- AD-541b episode anchoring.
- HXI top-bar layout (additive — adds one span after Entropy).

---

## Tracking

- PROGRESS.md — AD-742e entry under Wave 174.
- DECISIONS.md — AD-742e entry: in-memory v1, threshold-trigger UX, AD-742e-1 forward marker.
- docs/development/roadmap.md — flip AD-742e from forward-marker to shipped.
- File issue **post-build**: AD-742e-1 SQLite persistence for vision call log (small `vision_call_log` table, daily roll-up via SQL).

---

## Acceptance criteria

1. `VisionConsumer` has `_record_vision_call`, `get_budget_snapshot` methods.
2. Counters increment on every successful `_describe` LLM call.
3. `GET /api/perception/budget` returns the snapshot shape.
4. `<VisionBudgetBadge />` mounted in `DecisionSurface.tsx` after Entropy.
5. Badge hidden when `total_session == 0` (HXI Principle #5).
6. No emoji in the badge (HXI Principle #3 — text + color only).
7. +6 pytest + +6 vitest, all green.
8. **UI gate (BF-279, AD-738b): `cd ui; npx vitest run` AND `cd ui; npm run build` both green.**
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
10. ZERO new pip deps. ZERO new npm deps.

---

## Verified Against Codebase (2026-05-18)

```
grep -n "self._tier" src/probos/perception/consumer.py
  93: self._tier = vision_tier
grep -n "_describe" src/probos/perception/consumer.py
  255: description = await self._describe(sha)
  385: async def _describe(self, sha: str) -> str:
grep -n "@router.get" src/probos/routers/perception.py
  174: @router.get("/recent", ...)
  218: @router.get("/mode", ...)
grep -n "Routing Entropy" ui/src/components/DecisionSurface.tsx
  117: title="Routing Entropy \u2014 diversity of intent routing paths">
grep -n "from './icons/Glyphs'" ui/src/components/DecisionSurface.tsx
  6: import { Sparkle, StatusPending, StatusDone } from './icons/Glyphs';
```

All anchors confirmed against HEAD `65c97214`.
