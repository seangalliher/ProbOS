# AD-1201: surface pending approvals in the Bridge, with a dedicated approvals centre

**Repo:** OSS (`d:\ProbOS`), branch `main`, HEAD `b2bbe405`
**Issue:** #1141. Follows BF-710 (#1119).

---

## Problem

BF-710 made the approval panels reachable by mounting them in a fixed top-right container at
`top: 12, right: 12, zIndex: 26`. That is the exact position of the AD-325 Bridge toggle
(`IntentSurface.tsx:943`, `top: 12, right: 12, zIndex: 25`), so the approval stack now covers the
BRIDGE button completely.

It also reads as a raw stack of cards floating over the canvas, competing with the Bridge rather
than living in it.

**Captain, on seeing it:**

> There is already a notifications area in the bridge, I thought maybe they would show up here and
> then if I clicked on one it could pop out a dedicated approvals center experience.

That is the better design, and every piece of machinery it needs already exists.

## Why the Bridge is the right home

`BridgePanel` is already the attention surface. It computes `attentionTasks` and `attentionNotifs`
and renders them as activity-feed sections beneath the six command stations, under a comment that
names the principle:

```
{/* ── ACTIVITY FEED — alert-driven, NOT stations (HXI #9). These rise
    and recede with system state; they carry no stationId. ── */}
```

Pending approvals are exactly that shape. And Zone 4 of `docs/design/hxi-glass-bridge.md` — the
target design — specifies the Bridge Panel as *"Attention · Active · Notifs · Kanban · Recent"*,
so this placement survives the AD-1202 design pass rather than being redone by it.

## The expand idiom already exists

`BridgeSection` takes `onExpand`, rendered as a ↗ affordance titled *"Expand to full view"*.
Three stations use it (`components/bridge/stations.tsx`):

```tsx
onExpand: () => useStore.setState({ wardRoomOpen: true, wardRoomView: 'channels' }),
onExpand: () => useStore.setState({ mainViewer: 'work' }),      // onExpandLabel: 'Work Board'
onExpand: () => useStore.setState({ mainViewer: 'system' }),    // onExpandLabel: 'System'
```

"Summary in the Bridge, click to open the full experience" is the established pattern. Adopt it.

---

## Decision

### 1. Remove the fixed top-right wrapper

Delete the BF-710 container from `App.tsx` — the `<div style={{ position: 'fixed', top: 12,
right: 12, zIndex: 26, ... }}>` holding both panels. It was the wrong placement.

The BRIDGE toggle must be unobstructed afterwards.

### 2. Add an APPROVALS activity-feed section to `BridgePanel`

Beside ATTENTION and NOTIFICATIONS. **No `stationId`** — that is what gives it the activity-feed
treatment rather than the station accent edge (`BridgePanel.tsx`, the `borderLeft: stationId ?
... : undefined` line).

Renders only when there are pending requests; recedes to nothing when there are none — matching
`attentionCount > 0 &&` for the ATTENTION section.

Each row is a **compact summary**: who asked, what kind, how long ago. Not the full card. The
approve/deny controls belong in the centre, not the feed.

### 3. `onExpand` opens a dedicated approvals centre

A store flag matching `wardRoomOpen` / `shipsLockerOpen` / `mcpServersOpen`. The centre is where
the existing approve/deny controls, the reason field and the request detail live — reuse
`CapabilityRequestPanel` and `SkillRequestPanel` as its content rather than rewriting them.

### 4. Include pending approvals in the Bridge badge

`IntentSurface.tsx` currently computes:

```tsx
const badgeCount = needsAttentionCount + unreadCount;
```

Add pending approvals, so the BRIDGE button reads `BRIDGE (n)` when an agent is waiting. That is
the persistent, non-occluding indicator the floating box was trying to be.

### 5. Where the data comes from

Both panels fetch their own state today. The section and the badge need the count too. Decide
deliberately and say which you chose: a shared store slice fed by one poller, or each consumer
fetching. **Prefer one poller** — three independent 10s polls against two endpoints is wasteful
and can disagree about the count mid-cycle.

Whatever you choose, keep the 10s cadence established by `CrewRosterPanel` / `FullSystem` /
`BridgeSystem`, and clear timers on unmount.

---

## Acceptance criteria

1. The fixed top-right wrapper is gone; the BRIDGE toggle is unobstructed
2. APPROVALS section appears in `BridgePanel` only when requests are pending, and disappears when
   none are
3. It carries **no `stationId`** — activity-feed treatment, not a station
4. `onExpand` opens the approvals centre
5. The centre carries working approve/deny; approving posts to
   `POST /api/capability-requests/{id}/decide` and the request leaves the list
6. Both capability requests and skill requests are represented in the section and the centre
7. The Bridge badge includes pending approvals
8. **The reachability guard survives.** BF-710 added `App.bf710.test.tsx` asserting `App.tsx`
   mounts the panels. That assertion is about to become false by design. **Replace it, do not
   delete it** — assert instead that the approvals surface is reachable from `BridgePanel`. The
   property being pinned is unchanged: something in shipped code must render the approval
   surface. The BF-710 lesson holds — `render(<Panel />)` mounts a component by definition and can
   never detect a missing mount, so the assertion must be about the caller
9. No leaked timers — unmount, advance time, assert no further fetches

Expected: **10–14 Vitest tests.** No Python changes are expected; say so if that turns out wrong.

### Gates

```powershell
cd ui
npx vitest run
npm run build
```

Then ONE full Python gate to prove no backend regression, run **synchronously**, piped through
`Tee-Object -FilePath <log>` (never `Select-Object` — a buffering pipe silences the stream and
gets a healthy run backgrounded).

**Baseline is 22,548 NODES** (BF-708's gate: 22,548 passed, 0 failed — carry NODES, not passed).
Reconcile and show the arithmetic. If you add no Python tests the total should be unchanged.

---

## Do NOT build

- **Do not** fix BF-709 (#1115). The request *title* is currently the whole assembled prompt,
  including the visual-context block — that is why the cards read as noise. It has its own issue.
  **Do not paper over it with truncation here**; a truncated assembled prompt is still noise
- **Do not** start AD-1202 (#1142), the control-primitives work. Use the existing `BridgeSection`
  styling as-is. The aesthetic question is open and is the Captain's call
- **Do not** add a WebSocket consumer for `CAPABILITY_REQUEST_FILED` — still poll-driven
- **Do not** change the decide endpoint, `_STANDING_RULE_KINDS` (AD-1175), or any backend
  approval semantics
- **Do not** restyle the other Bridge sections
- **Do not** edit `PROGRESS.md`, `DECISIONS.md`, or the roadmap
- **Do not** stage `config/system.yaml` (skip-worktree) or this prompt

## Notes

- There are **7 real pending `continue` requests** on the reference vessel. Do not delete or
  expire them — they are the live test data
- str-replace end-anchor trap: whatever appears at either END of `oldString` must reappear in
  `newString`. `App.tsx`'s panel list and `BridgePanel`'s section list are both runs of
  near-identical lines — read the whole block before editing and verify the neighbours survived
- Stage before the full Python gate (`test_ad1123_bounded_federation_relay.py` reads *unstaged*
  diff)

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
