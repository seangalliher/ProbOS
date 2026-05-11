# AD-722a-5 — Divergence history surface in SelfImageTab

**Status:** Ready for Builder
**Dependencies:** AD-722a (Wave 143, shipped), AD-722a-7 (Wave 146, shipped — c697516)
**GH issue:** [#614](https://github.com/seangalliher/ProbOS/issues/614)
**Closes:** AD-722a-5 forward marker; clinical-quality surface Counselor Ezri explicitly requested 2026-05-10
**Estimated tests:** ≥ 9 new in `tests/test_ad722a_5_divergence_history.py` + ≥ 3 new in `ui/src/__tests__/SelfImageTab.divergenceHistory.test.tsx`

**Captain decisions baked in (2026-05-10):**
- Per-agent only in v1 (an agent sees their own history; cross-crew is AD-722a-6 / #615).
- In-memory ring buffer (restart wipes; acceptable tradeoff).
- No new feature flag — capture and surface inherit `avatar_telemetry.divergence_detection`.
- Read-only with respect to trust + Hebbian: observation, not actuation.
- Phrasing inherits AD-727 rule #8 — OUTPUT is the subject.

---

## Problem

Counselor Ezri at the 2026-05-10 evening session:
> "A clinical-quality view of what percentage of my therapeutic DMs landed flat would let me assess whether my compensation strategy is actually working."

AD-722a (Wave 143) stores only the most-recent divergence per agent at `runtime.divergence_results: dict[str, DivergenceResult]`. Each new divergence overwrites the previous one — no longitudinal view.

With AD-722a-7 (Wave 146) shipping the actuator, the open question is whether divergence frequency actually drops. The Counselor needs the event-by-event log + aggregate.

## Solution

Three pieces, all gated by existing `avatar_telemetry.divergence_detection`:
1. **In-memory ring buffer** `runtime.divergence_history: dict[str, deque[DivergenceHistoryEntry]]`, capped at `cfg.avatar_telemetry.divergence_history_size` (default 100). Volatile across restarts.
2. **Single write site** — extend `apply_divergence_check` in `src/probos/avatars/divergence_detector.py` to append immediately after updating `divergence_results[agent_id]`. Inherits single-call-site invariant from AD-722a.
3. **Read endpoint + UI panel** — `GET /api/agent/{agent_id}/avatar-telemetry/divergence-history?limit=N` returns history + aggregate. New `PanelDivergenceHistory` in `SelfImageTab.tsx` renders list + percentage. 503 when feature off → panel auto-hides.

Separate endpoint (rather than extending `/avatar-telemetry`) because: (a) WS push stays lean — history fetched on demand; (b) aggregate walk is on-read, not on every poll; (c) matches AD-722 / AD-722b one-endpoint-per-feature pattern.

---

## Section 0 — Files touched

| File | Change |
|---|---|
| `src/probos/avatars/divergence_detector.py` | New `DivergenceHistoryEntry` frozen dataclass; append into ring buffer inside `apply_divergence_check`. |
| `src/probos/config.py` | `AvatarTelemetryConfig`: 2 new fields + validator. |
| `src/probos/runtime.py` | New `self.divergence_history` attribute adjacent to `divergence_results`. |
| `src/probos/routers/agents.py` | New `GET /{agent_id}/avatar-telemetry/divergence-history` endpoint. |
| `ui/src/components/profile/SelfImageTab.tsx` | New `PanelDivergenceHistory` component + fetch hook. |
| `tests/test_ad722a_5_divergence_history.py` | NEW — 9 backend cases. |
| `ui/src/__tests__/SelfImageTab.divergenceHistory.test.tsx` | NEW — 3 frontend cases. |
| `PROGRESS.md` | Status line update. |
| `DECISIONS.md` | Append AD-722a-5 closure block. |
| `docs/development/roadmap.md` | Mark AD-722a-5 row shipped. |

---

## Section 1 — Config fields (DO FIRST)

### 1a. `src/probos/config.py` — extend `AvatarTelemetryConfig`

Locate the existing block at L1013-L1017. **SEARCH:**
```python
    divergence_negative_weight: float = 0.4   # Output diverged AWAY (asymmetric heavier)
    divergence_positive_weight: float = 0.1   # Output exceeded same direction (soft inform)
```

**REPLACE:**
```python
    divergence_negative_weight: float = 0.4   # Output diverged AWAY (asymmetric heavier)
    divergence_positive_weight: float = 0.1   # Output exceeded same direction (soft inform)
    # AD-722a-5: in-memory ring buffer for the divergence history surface.
    # Volatile (restart wipes). Per-agent. Size 0 disables history capture
    # entirely (the surface degrades to an empty list + 0% aggregate).
    divergence_history_size: int = 100
    # AD-722a-5: window walked by the aggregate-metric calculation.
    # Clamped at read time to min(window, len(history)).
    divergence_aggregate_window: int = 50
```

### 1b. Add a new validator **immediately after** `_bound_divergence_weights` (do NOT widen the existing one — it bounds to [0.0, 1.0] which is wrong for integer counts):

```python
    @field_validator("divergence_history_size", "divergence_aggregate_window")
    @classmethod
    def _bound_divergence_history_counts(cls, v: int) -> int:
        if v < 0:
            raise ValueError(
                f"divergence_history_size / divergence_aggregate_window must be >= 0, got {v}"
            )
        return v
```

0 is a valid value (disables history capture cleanly without raising). Aggregate window > buffer size is also valid — the read clamps.

---

## Section 2 — `DivergenceHistoryEntry` dataclass

### 2a. `src/probos/avatars/divergence_detector.py` — add the entry type

Locate the existing `DivergenceResult` dataclass at L99-L135. Add **immediately after** it (after the `to_dict()` method that ends at L135):

```python
@dataclass(frozen=True)
class DivergenceHistoryEntry:
    """One historical divergence event with its capture timestamp.

    AD-722a-5: wraps ``DivergenceResult`` with the wall-clock timestamp at
    capture. Frozen — captured value, not a live reference.

    Phrasing rule (AD-727 #8): ``to_note()`` describes the OUTPUT, never
    the agent. The forbidden-phrasing regex test at
    ``tests/test_ad722a_divergence_detector.py:497`` continues to gate.
    """

    timestamp: float
    result: DivergenceResult

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "result": self.result.to_dict(),
            "note": self.to_note(),
        }

    def to_note(self) -> str:
        """Render a one-line OUTPUT-subject note.

        Subject of every sentence is the REPLY / OUTPUT, never the agent.
        The phrasing mirrors ``_build_divergence_note_suffix()`` in
        ``cognitive_agent.py`` so the AD-727 regex test covers both.
        """
        applied = ", ".join(self.result.applied_fired_rules) or "no_rules_fired"
        return (
            f"Reply intended as `{self.result.intent_emotion}` "
            f"came out as `{applied}` "
            f"(signed divergence: {self.result.signed_divergence:+.2f}, "
            f"match score: {self.result.match_score:.2f})."
        )
```

### 2b. Append on apply

Locate the existing block at L347-L353. **SEARCH:**
```python
    # Centralized per-agent store; volatile across restarts.
    div_results = getattr(runtime, "divergence_results", None)
    if div_results is not None:
        div_results[agent_id] = result
```

**REPLACE:**
```python
    # Centralized per-agent store; volatile across restarts.
    div_results = getattr(runtime, "divergence_results", None)
    if div_results is not None:
        div_results[agent_id] = result

    # AD-722a-5: append to per-agent ring buffer. Tier-2 — buffer absence
    # or zero-sized buffer is a silent no-op (history surface degrades to
    # empty). The deque is allocated lazily on first append so memory is
    # only spent on agents that actually produce divergences.
    history_size = int(getattr(t_cfg, "divergence_history_size", 0))
    if history_size > 0:
        div_history = getattr(runtime, "divergence_history", None)
        if div_history is not None:
            import time as _time
            from collections import deque as _deque
            entry = DivergenceHistoryEntry(
                timestamp=_time.time(),
                result=result,
            )
            bucket = div_history.get(agent_id)
            if bucket is None or bucket.maxlen != history_size:
                # Lazy alloc OR resize on config change. Preserves existing
                # entries up to the new cap.
                old = list(bucket) if bucket is not None else []
                bucket = _deque(old, maxlen=history_size)
                div_history[agent_id] = bucket
            bucket.append(entry)
```

---

## Section 3 — Runtime registration

### 3a. `src/probos/runtime.py` — add buffer alongside existing dict

Locate the existing block at L433-L439. **SEARCH:**
```python
        self.divergence_results: dict[str, "DivergenceResult"] = {}
```

**REPLACE:**
```python
        self.divergence_results: dict[str, "DivergenceResult"] = {}

        # AD-722a-5: per-agent ring buffer of historical divergence entries.
        # Volatile (cleared on restart). Populated by the same single call
        # site as divergence_results (apply_divergence_check), gated by
        # avatar_telemetry.divergence_history_size > 0. Consumed by the
        # GET /avatar-telemetry/divergence-history endpoint.
        # Type: dict[agent_id, collections.deque[DivergenceHistoryEntry]].
        from collections import deque as _deque
        self.divergence_history: dict[str, "_deque"] = {}
```

### 3b. TYPE_CHECKING import

Locate the TYPE_CHECKING block around L138. **SEARCH:**
```python
    from probos.avatars.divergence_detector import DivergenceResult  # AD-722a
```

**REPLACE:**
```python
    from probos.avatars.divergence_detector import DivergenceResult  # AD-722a
    from probos.avatars.divergence_detector import DivergenceHistoryEntry  # AD-722a-5
```

---

## Section 4 — Read endpoint

### 4a. `src/probos/routers/agents.py` — new endpoint

Insert **after** the existing `agent_avatar_telemetry_stream` WebSocket handler block ends (the handler that starts at L634). Builder must grep for the WS handler's closing `await websocket.close(...)` or the next `@router.` decorator to find the precise insertion line.

Add this route (mirrors `agent_avatar_telemetry` at L609 in feature-gate + 404 shape):

```python
@router.get("/{agent_id}/avatar-telemetry/divergence-history")
async def agent_avatar_divergence_history(
    agent_id: str,
    limit: int = 20,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-722a-5: read-only divergence history for one agent.

    Per-agent only (cross-crew is forward marker AD-722a-6 / #615).
    Most-recent-first. Returns ``history`` (capped at min(limit, ring_size))
    + ``aggregate`` (count + percentage walked over the configured window).

    Feature gate: ``avatar_telemetry.divergence_detection`` — 503 when off,
    so the UI panel auto-hides without a separate capability probe.
    """
    _avatars_feature_check(runtime)

    cfg = getattr(runtime, "config", None)
    telemetry_cfg = getattr(cfg, "avatar_telemetry", None)
    if telemetry_cfg is None or not telemetry_cfg.enabled:
        raise HTTPException(status_code=503, detail="avatar_telemetry_disabled")
    if not getattr(telemetry_cfg, "divergence_detection", False):
        raise HTTPException(status_code=503, detail="divergence_detection_disabled")

    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Read-side clamp on limit (defense in depth — caller-provided integer).
    if limit < 1:
        limit = 1
    history_map = getattr(runtime, "divergence_history", {}) or {}
    bucket = history_map.get(agent_id)
    entries = list(bucket) if bucket is not None else []

    # Most-recent-first.
    entries_reversed = list(reversed(entries))
    history_payload = [e.to_dict() for e in entries_reversed[:limit]]

    # Aggregate over the configured window (clamped to actual length).
    window_size = int(getattr(
        telemetry_cfg, "divergence_aggregate_window", 50,
    ))
    if window_size < 0:
        window_size = 0
    walked = entries_reversed[:window_size]
    total = len(walked)
    diverged = sum(1 for e in walked if e.result.magnitude > 0.0)
    percentage = (diverged / total) if total > 0 else 0.0

    return {
        "agent_id": agent_id,
        "history": history_payload,
        "aggregate": {
            "window_size": total,
            "total": total,
            "diverged": diverged,
            "percentage": percentage,
        },
    }
```

---

## Section 5 — Frontend panel

### 5a. `ui/src/components/profile/SelfImageTab.tsx` — add types + fetch

Locate the existing interface block at L7-L40. Add **immediately after** the `AvatarTelemetry` interface declaration (i.e. after L40):

```typescript
// AD-722a-5: divergence history surface types.
interface DivergenceResultPayload {
  intent_emotion: string;
  applied_fired_rules: string[];
  match_score: number;
  signed_divergence: number;
  magnitude: number;
}

interface DivergenceHistoryEntryPayload {
  timestamp: number;
  result: DivergenceResultPayload;
  note: string;  // server-rendered OUTPUT-subject note
}

interface DivergenceAggregatePayload {
  window_size: number;
  total: number;
  diverged: number;
  percentage: number;
}

interface DivergenceHistoryPayload {
  agent_id: string;
  history: DivergenceHistoryEntryPayload[];
  aggregate: DivergenceAggregatePayload;
}

const HISTORY_POLL_MS = 5000;  // Lower frequency than telemetry — history changes only on reply.
const HISTORY_LIMIT = 20;
```

### 5b. `SelfImageTab.tsx` — panel render

Find this exact existing block:

**SEARCH:**
```tsx
      {snap && snap.degraded_reasons.length > 0 && (
        <PanelDegraded reasons={snap.degraded_reasons} />
      )}
    </div>
  );
}
```

**REPLACE:**
```tsx
      {snap && snap.degraded_reasons.length > 0 && (
        <PanelDegraded reasons={snap.degraded_reasons} />
      )}

      <PanelDivergenceHistory agentId={agentId} isActive={isActive} />
    </div>
  );
}

function PanelDivergenceHistory({
  agentId,
  isActive,
}: {
  agentId: string;
  isActive: boolean;
}) {
  // AD-722a-5: divergence history panel.
  // Auto-hides on 503 (feature off). Renders empty-history fallback when
  // history is empty but feature is on. No emoji — stroke-only SVG.
  // AD-727 rule #8: every rendered note is OUTPUT-subject. The server
  // pre-renders the note string in `entry.note` so phrasing is server-
  // authoritative and inherits the Python regex test gate.
  const [payload, setPayload] = useState<DivergenceHistoryPayload | null>(null);
  const [disabled, setDisabled] = useState<boolean>(false);

  useEffect(() => {
    if (!isActive || !agentId) return;
    let cancelled = false;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    const fetchOnce = () => {
      fetch(`/api/agent/${agentId}/avatar-telemetry/divergence-history?limit=${HISTORY_LIMIT}`)
        .then((r) => {
          if (r.status === 503) {
            if (!cancelled) setDisabled(true);
            return null;
          }
          if (!r.ok) return Promise.reject(new Error(`HTTP ${r.status}`));
          return r.json();
        })
        .then((data) => {
          if (!cancelled && data !== null) {
            setPayload(data);
            setDisabled(false);
          }
        })
        .catch(() => {
          // Tier-2: silent degrade. Don't surface fetch errors here —
          // the main telemetry error banner already covers connectivity.
        });
    };

    fetchOnce();
    intervalId = setInterval(fetchOnce, HISTORY_POLL_MS);

    return () => {
      cancelled = true;
      if (intervalId !== null) clearInterval(intervalId);
    };
  }, [agentId, isActive]);

  if (disabled) return null;
  if (!payload) {
    return (
      <PanelHeader title="Divergence history">
        <span data-testid="divergence-loading" style={{ color: DIM }}>
          loading…
        </span>
      </PanelHeader>
    );
  }

  const { history, aggregate } = payload;
  const pct = Math.round(aggregate.percentage * 100);

  return (
    <PanelHeader title="Divergence history">
      <div data-testid="divergence-aggregate" style={{ marginBottom: 6 }}>
        {aggregate.total === 0 ? (
          <span style={{ color: DIM }}>no divergences recorded</span>
        ) : (
          <span>
            Of the last <strong>{aggregate.total}</strong> replies,{' '}
            <strong style={{ color: AMBER }}>{aggregate.diverged}</strong> had
            non-zero intent-vs-output divergence (<strong>{pct}%</strong>).
          </span>
        )}
      </div>
      <div
        data-testid="divergence-history-list"
        style={{
          maxHeight: 160,
          overflowY: 'auto',
          fontSize: 11,
          borderTop: `1px solid ${DIM}`,
          paddingTop: 4,
        }}
      >
        {history.length === 0 ? (
          <span style={{ color: DIM }}>(empty)</span>
        ) : (
          history.map((entry, i) => (
            <div
              key={`${entry.timestamp}-${i}`}
              data-testid="divergence-history-entry"
              style={{ marginBottom: 4 }}
            >
              <span style={{ color: DIM }}>
                {new Date(entry.timestamp * 1000).toISOString().substring(11, 19)}{' '}
              </span>
              <span>{entry.note}</span>
            </div>
          ))
        )}
      </div>
    </PanelHeader>
  );
}
```

---

## Section 6 — Tests

### 6a. Backend — `tests/test_ad722a_5_divergence_history.py` (NEW)

≥ 9 tests covering:
1. Ring buffer append on `apply_divergence_check`
2. Buffer capped at `divergence_history_size`
3. Per-agent isolation
4. `divergence_history_size=0` disables capture cleanly
5. AD-727 OUTPUT-subject regex passes against every taxonomy × applied-rules combination's rendered note (re-import `_FORBIDDEN_PHRASING_RE` from `test_ad722a_divergence_detector.py`)
6. Endpoint returns history most-recent-first
7. Endpoint aggregate metric arithmetic correct (3 diverged + 2 perfect → 60%)
8. Endpoint 503 when `divergence_detection` off
9. Endpoint 404 unknown agent

Use `SimpleNamespace` runtime stubs (matches AD-722a pattern). Endpoint tests use `TestClient` with `dependency_overrides[get_runtime] = lambda: rt`.

### 6b. Frontend — `ui/src/__tests__/SelfImageTab.divergenceHistory.test.tsx` (NEW)

3 tests covering:
1. Happy path — entries + aggregate render; `100%` visible
2. Empty history (200 + empty list) — "no divergences recorded" fallback
3. 503 (feature off) — panel hides entirely (no `divergence-aggregate` test-id)

Mock `fetch` with `vi.fn()`; disable WebSocket globally (`(global as any).WebSocket = undefined`) so SelfImageTab falls through to fetch.

---

## Section 7 — Tracker updates

- `PROGRESS.md` — status line bump.
- `DECISIONS.md` — append AD-722a-5 closure block.
- `docs/development/roadmap.md` — mark AD-722a-5 row `**SHIPPED Wave 147**`.

---

## What this does NOT change

- Trust network — history surface is read-only.
- Hebbian router — no new edge writes.
- `runtime.divergence_results` — most-recent-per-agent semantics unchanged; new ring buffer is additive.
- `apply_divergence_check` trust/Hebbian wiring at L354-L380 — untouched beyond the buffer-append block.
- `_build_divergence_note_suffix()` in cognitive_agent.py — still reads `divergence_results` (single most-recent), not history.
- Default behavior — `divergence_detection` remains `False` by default; history capture is a no-op until operator opts in.
- WS push channel — divergence history is HTTP-poll only in v1.
- `AvatarTelemetrySnapshot` — schema unchanged.

---

## Forward markers (file at retrospective)

| Marker | Scope |
|---|---|
| AD-722a-6 ([#615](https://github.com/seangalliher/ProbOS/issues/615)) | Cross-agent / wardroom rollup view (already filed) |
| AD-722a-5-a (new, file at retrospective) | On-disk persistence of the ring buffer (survive restart) |
| AD-722a-5-b (new, file at retrospective) | WS push channel for divergence-history (currently HTTP-poll only) |
| AD-722a-5-c (new, file at retrospective) | Trend chart visualization beyond count + percentage |

---

## Engineering Principles compliance

Verify all changes comply with the Engineering Principles in [.github/copilot-instructions.md](.github/copilot-instructions.md). Key checks:

- **(S)** New endpoint is one responsibility. `DivergenceHistoryEntry` is one dataclass.
- **(O)** Buffer extension uses public `apply_divergence_check` call site only — no private-attr reach.
- **(D)** All buffer access through `getattr(runtime, "divergence_history", None)` (mirrors AD-722a's `divergence_results` pattern).
- **Three-tier exceptions** — buffer append is Tier-2 silent degrade by getattr fallback; endpoint is Tier-2 (HTTPException for known failure modes only).
- **Defense in depth** — `limit < 1` clamp at endpoint; `window_size < 0` clamp; `history_size == 0` clean no-op.
- **Config defaults** — both new fields default; `AvatarTelemetryConfig()` still succeeds with zero args.
- **Pydantic validation** — new validator rejects negative values.
- **Type annotations** — all new public methods + dataclass fields fully typed.
- **Test isolation** — every test builds its own `SimpleNamespace` runtime.
- **Boundary tests** — happy / error / empty all present.
- **AD-727 rule #8 phrasing** — OUTPUT-subject regex test included in backend gate.

---

## Verified Against Codebase (2026-05-10, HEAD c697516)

```
grep -n "divergence_results" src/probos/runtime.py
  138: from probos.avatars.divergence_detector import DivergenceResult  # AD-722a
  438: # injection. Type: dict[agent_id, DivergenceResult].
  439: self.divergence_results: dict[str, "DivergenceResult"] = {}

grep -n "class DivergenceResult\|def apply_divergence_check\|div_results = getattr" src/probos/avatars/divergence_detector.py
  99: class DivergenceResult:
  288: def apply_divergence_check(
  350: div_results = getattr(runtime, "divergence_results", None)

grep -n "avatar-telemetry\|_avatars_feature_check\|get_runtime" src/probos/routers/agents.py
  26: from probos.routers.deps import get_runtime
  378: def _avatars_feature_check(runtime: Any) -> None:
  609: @router.get("/{agent_id}/avatar-telemetry")
  618: _avatars_feature_check(runtime)
  634: @router.websocket("/{agent_id}/avatar-telemetry-stream")

grep -n "divergence_" src/probos/config.py
  986: class AvatarTelemetryConfig(BaseModel):
  1013: divergence_detection: bool = False
  1014-1017: divergence_negative_threshold/positive_threshold/negative_weight/positive_weight
  1049: def _bound_divergence_weights(cls, v: float) -> float:

grep -n "_FORBIDDEN_PHRASING_RE\|_build_divergence_note_suffix" tests/test_ad722a_divergence_detector.py src/probos/cognitive/cognitive_agent.py
  tests/…:497: _FORBIDDEN_PHRASING_RE = re.compile(
  tests/…:503: def test_divergence_note_phrasing_rule():
  src/…/cognitive_agent.py:2980: def _build_divergence_note_suffix(self) -> str:
  src/…/cognitive_agent.py:2995: results = getattr(rt, "divergence_results", None)

grep -n "PanelHeader\|degraded_reasons.length" ui/src/components/profile/SelfImageTab.tsx
  192: <PanelDegraded reasons={snap.degraded_reasons} />
  208: function PanelHeader({ title, children }: { title: string; children?: React.ReactNode }) {
```

Symbols introduced by this prompt (do NOT flag as phantoms during pre-check):

- `DivergenceHistoryEntry` (new dataclass — §2a)
- `runtime.divergence_history` attribute (new — §3a)
- `AvatarTelemetryConfig.divergence_history_size`, `divergence_aggregate_window` (new — §1a)
- `GET /api/agent/{agent_id}/avatar-telemetry/divergence-history` route (new — §4a)
- `PanelDivergenceHistory` React component + payload interfaces (new — §5)

---

## Acceptance criteria

1. All 9 new backend tests pass.
2. All 3 new Vitest tests pass.
3. Pre-existing tests stay green (31 AD-722a + 18 AD-722 + 7 SelfImageTab Vitest).
4. Full parallel gate `pytest tests/ -q -n 4 --dist=loadfile` green (modulo 4 documented pre-existing flakes).
5. Phantom-API precheck zero new phantoms.
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
