# AD-388: Glass Overlay & Center Task Cards

## Overview

Layer a frosted glass surface over the existing 3D orb mesh to display active
task cards in the center of the viewport. This is Phase 1 of the Glass Bridge
progressive enhancement — the foundation for all subsequent Glass Bridge ADs
(389-392).

**Critical constraint:** The existing CognitiveCanvas (orbs, Hebbian arcs,
animations) remains untouched. The glass is a **new layer on top** at z-index 1,
between the canvas (z=0) and the controls (IntentSurface, BridgePanel at z=2+).
The mesh breathes underneath, visible through the frosted surface.

Full design spec: `docs/design/hxi-glass-bridge.md`

## Architecture

### New Component: GlassLayer

Create `ui/src/components/GlassLayer.tsx` — a full-viewport overlay that renders
active task cards on a frosted glass surface.

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│            (orb mesh visible through frost)              │
│                                                         │
│                 ╔═══════════════════╗                    │
│                 ║   ACTIVE TASK      ║                    │
│                 ║   "Refactor the    ║                    │
│                 ║    payment svc"    ║                    │
│                 ║                     ║                    │
│                 ║   Step 2/5  ██░░░  ║                    │
│                 ║   ● working  1m    ║                    │
│                 ╚═══════════════════╝                    │
│                                                         │
│          ┌──────────┐    ┌──────────┐                   │
│          │ Task 2   │    │ Task 3   │                   │
│          │ ◐ 40%    │    │ ○ queued │                   │
│          └──────────┘    └──────────┘                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Positioning:**
- `position: absolute; inset: 0; z-index: 5`
- `pointer-events: none` on the container (cards themselves are `pointer-events: auto`)
- This sits above CognitiveCanvas (z=0) but below IntentSurface/BridgePanel controls

**Frost effect:**
- `backdrop-filter: blur(Npx)` where N is dynamic based on active task count
- No tasks: `blur(0)` — fully transparent, mesh dominates (current experience)
- 1-2 tasks: `blur(2px)` — light frost, mesh clearly visible
- 3-5 tasks: `blur(4px)` — moderate frost, focus shifts to cards
- 6+ tasks: `blur(6px)` — heavier frost, glass becomes the primary surface
- Subtle noise texture overlay: a CSS pseudo-element with a low-opacity noise pattern
  (`background-image: url('data:image/svg+xml,...')` or CSS gradient noise)
- Background: `rgba(10, 10, 18, 0.0)` at zero tasks, graduating to `rgba(10, 10, 18, 0.15)` at 6+ tasks

### GlassTaskCard Component

Create `ui/src/components/glass/GlassTaskCard.tsx` — a center-stage task card
rendered on the glass surface. Uses existing `AgentTaskView` data from the store.

**Card design:**
- Glass morphism: `background: rgba(26, 26, 46, 0.7)`, `backdrop-filter: blur(12px)`,
  `border: 1px solid rgba(255, 255, 255, 0.08)`
- Department-colored left border (3px) using existing `DEPT_COLORS` from
  `bridge/BridgeCards.tsx`
- Hard geometric corners — `border-radius: 2px` (NeXTSTEP precision, not rounded)
- Subtle depth: `box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4)` (parallax shadow)

**Card content:**
- Top row: status dot (pulsing amber for `working`, static colors for others) + AD number (if > 0) + title (truncated at 50 chars)
- Middle: progress bar (step_current / step_total) with department-colored fill
- Bottom row: agent_type + elapsed time + department name (monospaced, dimmed)
- Attention indicator: if `requires_action`, the card border pulses amber
  (`animation: glass-attention 2s ease-in-out infinite`)

**Typography:**
- Title: `'Inter', sans-serif`, 14px, weight 600, color `#e0e0e0`
- System data (agent type, time, department): `'JetBrains Mono', monospace`, 10px, weight 400, color `#808090`
- AD number: `'JetBrains Mono', monospace`, 10px, color matches department

### Multi-Task Constellation Layout

When multiple tasks are active, they arrange as a **constellation** around the
viewport center:

- **1 task:** Centered horizontally, at roughly 40% from top (slightly above center)
- **2 tasks:** Side by side, centered, 16px gap
- **3 tasks:** Primary task centered and slightly elevated, two secondary tasks
  flanking below (inverted triangle)
- **4-5 tasks:** Grid-like arrangement, most urgent (highest priority or
  `requires_action`) slightly elevated with larger card
- **6+ tasks:** Compact grid, cards shrink slightly (scale 0.9)

**Urgency elevation:** Tasks with `requires_action === true` render slightly
higher (translateY -8px) and with a brighter amber border glow. This implements
the "decisions rise" principle from the design spec.

**Card ordering:** Sort by:
1. `requires_action` tasks first
2. Then by `status`: working > review > queued > done > failed
3. Then by `priority` (lower number = higher priority)

### Fade-Through Behavior

- Tasks that complete (`status === 'done'` or `status === 'failed'`) should
  fade out over 800ms (`opacity 1 → 0`, `transform: translateY(20px)`)
- New tasks appearing should fade in over 300ms (`opacity 0 → 1`,
  `transform: scale(0.95) → scale(1)`)
- Use CSS transitions on the card wrapper, keyed by task `id`

### Click Interaction

- Clicking a glass task card opens the Bridge panel (`bridgeOpen: true`) and
  scrolls/highlights the corresponding task in the Attention or Active section
- This provides the drill-down path: glass card (overview) → Bridge panel (detail)

## Integration

### App.tsx Changes

Add `<GlassLayer />` between the canvas/FullKanban conditional and the
IntentSurface:

```tsx
{mainViewer === 'canvas' ? <CognitiveCanvas /> : <FullKanban />}
<GlassLayer />        {/* NEW — z=5, between canvas and controls */}
<IntentSurface />
<DecisionSurface />
```

The GlassLayer only renders when `mainViewer === 'canvas'`. When the main viewer
is `kanban`, the glass is not needed — the kanban already shows tasks.

### Store: No Changes

The glass layer reads `agentTasks` from the existing Zustand store. No new state
fields needed. The frost level is derived from `agentTasks?.length ?? 0`.

### Existing Components: No Changes

Do NOT modify:
- `CognitiveCanvas.tsx` — the mesh layer stays exactly as-is
- `IntentSurface.tsx` — the command surface stays as-is
- `BridgePanel.tsx` — the Bridge panel stays as-is
- `useStore.ts` — no new state fields for this AD

## File Plan

| Action | File | Description |
|--------|------|-------------|
| CREATE | `ui/src/components/GlassLayer.tsx` | Frost overlay + constellation layout |
| CREATE | `ui/src/components/glass/GlassTaskCard.tsx` | Individual task card on glass |
| MODIFY | `ui/src/App.tsx` | Add `<GlassLayer />` between canvas and IntentSurface |
| CREATE | `ui/src/__tests__/GlassLayer.test.tsx` | Tests for glass layer |

## Acceptance Criteria

1. When `mainViewer === 'canvas'` and there are active agent tasks, frosted glass
   task cards appear centered on the viewport over the 3D mesh
2. The 3D mesh (orbs, arcs, animations) remains fully visible and interactive
   beneath the glass — `pointer-events: none` on the glass container ensures
   orbit controls still work
3. Frost level increases dynamically with task count (0 tasks = no frost)
4. Cards show: status dot, AD number, title, progress bar, agent type, elapsed time, department
5. Cards with `requires_action` float higher and pulse amber
6. Task appearance/disappearance is animated (300ms in, 800ms out)
7. Clicking a glass card opens the Bridge panel
8. Glass layer does NOT render when `mainViewer === 'kanban'`
9. All text uses the correct typography: Inter for titles, JetBrains Mono for system data
10. OLED-native: no visible background when zero tasks, true black (#0a0a12) shows through

## Test Requirements

Create `ui/src/__tests__/GlassLayer.test.tsx` with at minimum:

1. **Glass hidden when no tasks** — renders nothing when agentTasks is null/empty
2. **Glass hidden in kanban mode** — renders nothing when mainViewer is 'kanban'
3. **Single task centered** — renders one GlassTaskCard when one task exists
4. **Multiple tasks shown** — renders correct count of cards for multiple tasks
5. **Attention tasks elevated** — tasks with requires_action have the attention class/style
6. **Frost increases with tasks** — backdrop-filter blur value increases with task count
7. **Click opens bridge** — clicking a card sets bridgeOpen to true

Use the existing test patterns from `ui/src/__tests__/useStore.test.ts`.

## Do NOT Build

- **Do NOT** add DAG visualization (sub-task nodes around cards) — that is AD-389
- **Do NOT** add ambient color temperature or bridge states — that is AD-390
- **Do NOT** add scan lines, data rain, or chromatic aberration — that is AD-391
- **Do NOT** add trust-driven card sizing or Command Surface breathing — that is AD-392
- **Do NOT** add sound effects — that is AD-391
- **Do NOT** add a Context Ribbon at the top — that is AD-390
- **Do NOT** modify the CognitiveCanvas, IntentSurface, or BridgePanel components
- **Do NOT** add new state fields to useStore — derive everything from existing agentTasks
- **Do NOT** use emoji anywhere in the UI — all icons are SVG or Unicode geometric shapes
