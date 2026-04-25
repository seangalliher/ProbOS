# AD-389: DAG Visualization — Sub-Task Nodes on the Glass

## Overview

Add spatial sub-task node visualization around the center task cards on the
glass layer. When a task card is expanded (clicked), its `steps` array renders
as a ring of small nodes around the card, forming a living DAG. Active nodes
pulse, completed nodes dim, queued nodes are ghosted outlines. Dependency lines
connect nodes sequentially.

This is Phase 2 of the Glass Bridge. Builds directly on AD-388 (GlassLayer +
GlassTaskCard). Full design spec: `docs/design/hxi-glass-bridge.md`.

## Architecture

### Expand/Collapse State

Add an `expandedGlassTask` field to track which task card (if any) is showing
its DAG nodes. Only one task can be expanded at a time on the glass.

**Store change** (`useStore.ts`):
```ts
expandedGlassTask: string | null;  // task id, default null
```

### GlassTaskCard Click Behavior Change

Currently clicking a GlassTaskCard opens the Bridge panel. Change to:

- **Single click** → toggle expand/collapse of that task's DAG nodes on the
  glass (set `expandedGlassTask` to the task's `id`, or `null` if already
  expanded)
- **Double click** → open the Bridge panel (existing behavior, moved to
  `onDoubleClick`)
- When a different task is clicked, the previous one collapses and the new one
  expands

### New Component: GlassDAGNodes

Create `ui/src/components/glass/GlassDAGNodes.tsx` — renders the step nodes
around an expanded task card.

**Layout:** Nodes arrange in a ring around the parent task card. For N steps:
- Steps are positioned radially around the card center
- Radius: 120-160px from card center (scale slightly with step count)
- Nodes at top, clockwise, following execution order
- Sequential dependency lines connect node N to node N+1 as thin lines
  (1px, `rgba(255,255,255,0.1)`)

**Node design (each step):**
- Small circle: 28px diameter
- Background: `rgba(26, 26, 46, 0.8)` with `backdrop-filter: blur(8px)`
- Border: 1px solid based on status:
  - `done`: `rgba(72, 184, 96, 0.4)` (green, dimmed)
  - `in_progress`: department color, pulsing (`neural-pulse` animation)
  - `pending`: `rgba(255, 255, 255, 0.1)` (ghosted outline)
  - `failed`: `rgba(200, 64, 64, 0.5)` (red)
- Center icon: `●` (done, green), `◐` (in_progress, dept color), `○` (pending,
  dim), `✕` (failed, red)
- `pointer-events: auto` on each node

**Node label:** On hover, show the step's `label` as a small tooltip below the
node. JetBrains Mono, 10px, `#808090`. Also show duration if available
(`duration_ms > 0`).

**"Decisions rise" effect:** If the parent task has `requires_action === true`,
the entire DAG group (card + nodes) shifts upward by 20px with a smooth
transition. This is already partially handled by GlassTaskCard's `elevated`
prop, but apply it to the whole group now.

### Dependency Lines (SVG)

Render dependency lines as an SVG overlay within the DAG group. Lines connect
sequential nodes (step 0 → step 1 → step 2 → ...). Style:

- Stroke: `rgba(255, 255, 255, 0.08)` for pending connections
- Stroke: department color at 30% opacity for completed connections
- Stroke width: 1px
- No arrowheads — the clockwise order implies direction

### Fade Animations

- When a task expands: nodes appear one at a time, 80ms stagger, fading in from
  `opacity: 0; scale: 0.5` to `opacity: 1; scale: 1` (200ms each, ease-out)
- When collapsing: all nodes fade out simultaneously (150ms, ease-in)
- Use CSS transitions/animations, not JS animation libraries

### Integration with GlassLayer

Modify `GlassLayer.tsx`:
- Import and render `GlassDAGNodes` next to the expanded task's card
- The DAG nodes are siblings of the card wrapper `div`, positioned relative to
  the same constellation position
- When expanded, slightly increase the frost around the expanded card (optional:
  a subtle radial gradient darkening around the expanded area)

## File Plan

| Action | File | Description |
|--------|------|-------------|
| CREATE | `ui/src/components/glass/GlassDAGNodes.tsx` | Radial step nodes + dependency lines |
| MODIFY | `ui/src/components/glass/GlassTaskCard.tsx` | Single-click expand, double-click bridge |
| MODIFY | `ui/src/components/GlassLayer.tsx` | Render GlassDAGNodes for expanded task |
| MODIFY | `ui/src/store/useStore.ts` | Add `expandedGlassTask: string \| null` |
| CREATE | `ui/src/__tests__/GlassDAGNodes.test.tsx` | Tests for DAG visualization |

## Acceptance Criteria

1. Clicking a glass task card expands it — step nodes appear radially around the
   card as small circles
2. Each node reflects its step's status: done (green, filled), in_progress
   (pulsing, dept color), pending (ghosted outline), failed (red)
3. Thin dependency lines connect sequential nodes
4. Hovering a node shows the step label and duration as a tooltip
5. Double-clicking a card opens the Bridge panel
6. Only one task can be expanded at a time — clicking another collapses the first
7. Expanding animates nodes in with 80ms stagger; collapsing fades all out
8. Tasks with `requires_action` shift the entire DAG group upward (decisions rise)
9. The underlying mesh remains visible — nodes use backdrop-filter blur, not
   opaque backgrounds
10. Glass layer still works correctly with 0 tasks, 1 task, and multiple tasks

## Test Requirements

Create `ui/src/__tests__/GlassDAGNodes.test.tsx`:

1. **expandedGlassTask defaults to null** — initial state
2. **expandedGlassTask can be set** — toggle on/off
3. **only one expanded at a time** — setting a new id replaces the old one
4. **step status mapping** — verify done/in_progress/pending/failed produce
   correct visual indicators
5. **empty steps array** — no nodes rendered when task has no steps
6. **node count matches step count** — N steps = N nodes

## Do NOT Build

- **Do NOT** add ambient color temperature or bridge states — that is AD-390
- **Do NOT** add scan lines, data rain, or sound effects — that is AD-391
- **Do NOT** add trust-driven card sizing — that is AD-392
- **Do NOT** modify CognitiveCanvas, IntentSurface, or BridgePanel
- **Do NOT** add drag-to-reorder on nodes (future iteration)
- **Do NOT** use any animation library — CSS only
