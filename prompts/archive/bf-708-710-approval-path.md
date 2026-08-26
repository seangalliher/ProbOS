# BF-708 + BF-710: restore the approval path

**Repo:** OSS (`d:\ProbOS`), branch `main`, HEAD `52eb25cc`
**Type:** BF. Code + tests ONLY. **This prompt stays UNTRACKED** — do not `git add` it.
**Issues:** #1114 (BF-708), #1119 (BF-710)
**Plan:** `prompts/build-plan-2026-08-03.md` — this is the item sequenced ahead of every wave.

---

## Problem

An agent asks the Captain for permission and there is **no path at all** by which the Captain
learns of it. Three independent defects, each individually silent, combine into a total blackout.

Live evidence: **7 requests filed, 7 notices skipped, 0 delivered.**

```
AD-853: Capability request filed — counselor_co wants continue '...' (id=33febdbf-b52)
AD-857: capability-request notice skipped — event missing agent_id
```

### Defect 1 — the notifier reads the event at the wrong level (BF-708)

`capability_request_notifier.py:36`:

```python
payload = getattr(event, "data", None) or getattr(event, "payload", None) or {}
agent_id = payload.get("agent_id") or ""
if not agent_id:
    logger.warning("AD-857: capability-request notice skipped — event missing agent_id")
    return
```

**The event is a `dict`, not an object.** `runtime.py:1628` builds it as:

```python
event = {"type": event_type.value, "data": data or {}, "timestamp": time.time()}
```

`getattr(some_dict, "data", None)` returns `None`. So `payload` becomes `{}`, `agent_id` becomes
`""`, and every notice is dropped. The field is present and correct — `capability_request.py:347`
emits `{"id", "agent_id", "kind", "target", "work_item_id"}` — it is simply one level down from
where the notifier looks.

### Defect 2 — neither approval panel is mounted (BF-710)

`ui/src/App.tsx` mounts panels directly in JSX (`<AgentProfilePanel />`, `<WardRoomPanel />`,
`<McpServersPanel />`, ~18 of them). **`CapabilityRequestPanel` and `SkillRequestPanel` are not
among them.** Their only references in `ui/src` are their own definitions and their own tests.

Both already return `null` when loaded with zero requests
(`CapabilityRequestPanel.tsx:221-222`, `SkillRequestPanel.tsx:245-246`), so mounting them is
safe — they self-hide.

### Defect 3 — the panel never refreshes (found while verifying defect 2)

`CapabilityRequestPanel.tsx:204-206`:

```python
useEffect(() => {
  void load();
}, [load]);
```

`load` is a `useCallback` with `[]` deps, so it is stable and the effect runs **once on mount**.
There is no `setInterval` in either panel. The module docstring says *"polls
/api/capability-requests?status=pending"* — it does not poll.

So even with defects 1 and 2 fixed, a request filed after the panel mounted would never appear.

---

## Decision

Fix all three. Any one left in place leaves the Captain blind.

### 1. The notifier accepts the real event shape

Read `data` from a dict event as well as an object event. Keep the object path — do not assume
every producer is a dict; some listeners in this codebase receive dataclass-shaped events.

Prefer a small named helper over an inline chain, because the same "dict or object" question will
recur for any other `add_event_listener` consumer. Handle: dict with `data`, dict with `payload`,
object with `.data`, object with `.payload`, and a bare dict of domain fields.

Keep the honest-degrade behaviour: a genuinely absent `agent_id` still skips and still warns.
**The warning must remain** — it is what surfaced this defect.

### 2. Mount both panels

Add `<CapabilityRequestPanel />` and `<SkillRequestPanel />` to `App.tsx` alongside the other
panels. Match the existing idiom exactly — no new registry, no conditional wrapper. They gate
themselves.

### 3. Make the panels refresh

Add a bounded poll so a request filed after mount appears. Match whatever interval the codebase
already uses for similar polling surfaces — grep for `setInterval` in `ui/src` and follow the
established pattern rather than inventing a cadence. Clear the interval on unmount.

**Do not** wire a WebSocket event path for this. `CAPABILITY_REQUEST_FILED` is emitted, but adding
a live-push consumer is a larger change and would repeat the BF-703 two-shell hazard. A poll is
the honest small fix; note the push option for later.

---

## Target files

| File | Change |
|---|---|
| `src/probos/capability_request_notifier.py` | event-shape helper + use it |
| `ui/src/App.tsx` | mount both panels |
| `ui/src/components/capability/CapabilityRequestPanel.tsx` | bounded poll + cleanup |
| `ui/src/components/skill/SkillRequestPanel.tsx` | bounded poll + cleanup |
| `tests/test_bf708_capability_notice.py` | NEW |
| `ui/src/__tests__/` | mount + poll tests (place per existing convention) |

---

## Acceptance criteria

### The test that matters most

**Drive the REAL event through the REAL notifier.** The existing notifier tests construct the
event themselves and supply `agent_id` at whatever level the notifier reads — which is exactly
why the suite was green while production dropped every notice. This is the audit's dominant
shape: the test double is more capable than production.

The new test must build the event **the way `runtime._emit_event` builds it** — ideally by
calling the real emit path, or at minimum by constructing
`{"type": ..., "data": {...}, "timestamp": ...}` and asserting that shape matches what
`runtime.py:1628` produces. If the runtime's construction changes, this test should fail.

### Python

1. A dict event with `data.agent_id` → notice is **delivered**, not skipped
2. An object event with `.data.agent_id` → still delivered (no regression)
3. A dict event with `payload` instead of `data` → delivered
4. A bare dict of domain fields → delivered
5. A genuinely absent `agent_id` → still skipped, **and still warns**
6. `ward_room is None` → still skips with its own distinct warning
7. End-to-end: `file_request(kind="continue", ...)` through the real store, with a listener
   registered the way `_wire_capability_request_notifier` registers it, results in a delivered
   notice. This is the test that would have caught the original defect.

### UI

8. `App.tsx` renders `CapabilityRequestPanel` and `SkillRequestPanel`. **Assert the mount, not
   the component** — a test that does `render(<CapabilityRequestPanel />)` mounts it by
   definition and can never detect that production does not. Either render `App` and assert the
   panels appear, or assert on `App.tsx` source that both are present in the JSX. State in the
   test docstring which property is being pinned and why the component-level test cannot.
9. A request filed after mount appears on the next poll (fake timers).
10. The interval is cleared on unmount — no leaked timer.
11. Both panels still render `null` when there are no pending requests.

Expected: **10–14 new tests** across Python and Vitest.

### Gates

```powershell
$env:PROBOS_DATA_DIR="$env:TEMP\bf708_$(Get-Random)"; $env:PROBOS_EMBEDDINGS='local'
& d:/ProbOS/.venv/Scripts/python.exe -m pytest `
  tests/test_bf708_capability_notice.py `
  tests/test_ad853_capability_requests.py `
  tests/test_ad857_capability_notifier.py `
  tests/test_ad1175_standing_rule_kinds.py `
  tests/test_ad1164_continue_or_ask.py `
  -q -n 0
```

(Substitute real paths for any that do not exist and **say so** — do not silently drop a gate.)

UI: `cd ui && npx vitest run` then `npm run build`.

Then ONE full Python gate, run **synchronously**. Pipe through `Tee-Object -FilePath <log>`,
never `Select-Object` — a buffering pipe silences the stream and gets a healthy run backgrounded.

**Baseline is 22,529 NODES** (AD-1176's gate: 22,529 passed, 0 failed — carry NODES, not passed).
Reconcile `22,529 + <new tests> == passed + failed` and show the arithmetic.

---

## Do NOT build

- **Do not** add a WebSocket/live-push consumer for `CAPABILITY_REQUEST_FILED`. Larger change,
  and it repeats the BF-703 two-shell hazard. Note it as a follow-up
- **Do not** fix BF-709 (#1115) here — the request *title* carrying the assembled prompt is a
  separate issue with its own fix (reuse `_promotion_request_text`'s shape)
- **Do not** change `_STANDING_RULE_KINDS` (AD-1175) or the decide endpoint's semantics
- **Do not** redesign the approval surface. HXI Design Principle #9 (alert-driven layout) may
  eventually want something richer; this restores the path that exists
- **Do not** remove the `AD-857` skip warning — it is the diagnostic that found this
- **Do not** edit `PROGRESS.md`, `DECISIONS.md`, or the roadmap
- **Do not** stage `config/system.yaml` (skip-worktree) or this prompt

## Notes

- Stage before the full gate (`test_ad1123_bounded_federation_relay.py` reads *unstaged* diff)
- str-replace end-anchor trap: whatever appears at either END of `oldString` must reappear in
  `newString`. `App.tsx`'s panel list is a run of near-identical lines — read the whole block
  before editing and verify the neighbours survived
- There are 7 real pending `continue` requests on the reference vessel. After this lands they
  should become visible. Do not delete or expire them as part of the fix

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
