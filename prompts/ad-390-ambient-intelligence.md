# AD-390: Ambient Intelligence & Bridge States

## Overview

Add ambient visual intelligence to the glass layer: the system's state is
glanceable in under 1 second without reading a single number. Three bridge
states drive the visual mood. A Context Ribbon provides dense system telemetry
at the top edge. A return-to-bridge briefing card appears after Captain absence.
Completion celebrations briefly bloom the mesh on task success.

This is Phase 3 of the Glass Bridge. Builds on AD-388 (GlassLayer) and AD-389
(DAG nodes). Full design spec: `docs/design/hxi-glass-bridge.md`.

## Architecture

### Bridge State Derivation

The bridge has three ambient states derived from existing store data. **No new
backend data needed** — derive entirely from `agentTasks` and `notifications`.

```
State        │ Condition                                     │ Visual Feel
─────────────┼───────────────────────────────────────────────┼────────────────
IDLE         │ No active tasks (agentTasks null/empty or     │ Cool cyan edges,
             │ all done/failed)                              │ mesh dominates
─────────────┼───────────────────────────────────────────────┼────────────────
AUTONOMOUS   │ Active tasks exist but NONE have              │ Golden warmth,
             │ requires_action === true                      │ "crew has it"
─────────────┼───────────────────────────────────────────────┼────────────────
ATTENTION    │ Any task has requires_action === true OR      │ Amber edge glow,
             │ any notification has type action_required     │ Captain needed
```

Add a derived helper function (NOT new store state — compute on render):
```ts
type BridgeState = 'idle' | 'autonomous' | 'attention';
function deriveBridgeState(tasks: AgentTaskView[] | null, notifications: NotificationView[] | null): BridgeState
```

### New Component: ContextRibbon

Create `ui/src/components/glass/ContextRibbon.tsx` — a dense HUD strip across
the top of the glass layer (Zone 1 from the design spec).

**Layout:** Full width, 32px height, positioned at top of glass layer.

**Content (left to right):**
- Bridge state indicator: colored dot + label (`IDLE` / `AUTONOMOUS` / `ATTENTION`)
- Agent count: `{agents.size} agents` (from store)
- Active task count: `{N} active` (derived from agentTasks)
- Attention count: `{N} attention` (requires_action tasks + action_required notifications) — only show if > 0
- System mode: `{systemMode}` (from store, e.g., "active", "dreaming")

**Styling:**
- Background: `rgba(10, 10, 18, 0.5)` with `backdrop-filter: blur(8px)`
- Text: JetBrains Mono, 10px, `#666680`, tracking +1px
- State dot colors: idle = `#38c8c0` (cyan), autonomous = `#d4a029` (gold), attention = `#f0ae40` (amber)
- Separator: `·` character (middle dot) in `#333` between items
- `pointer-events: auto` (the ribbon is interactive — items show details on hover in future ADs)
- The ribbon edge (bottom border) glows with the bridge state color at low opacity

### Ambient Edge Glow

Add a subtle edge glow to the glass layer that reflects the bridge state. This
is the "glanceable in 1 second" feature — the Captain sees the color without
reading anything.

**Implementation:** A CSS `box-shadow: inset` on the glass layer container:
- IDLE: `box-shadow: inset 0 0 80px rgba(56, 200, 192, 0.04)` (barely visible cyan)
- AUTONOMOUS: `box-shadow: inset 0 0 80px rgba(212, 160, 41, 0.06)` (golden warmth)
- ATTENTION: `box-shadow: inset 0 0 60px rgba(240, 174, 64, 0.1)` (amber, more visible)

Transition between states over 1200ms (linear).

### Return-to-Bridge Briefing Card

When the Captain has been away (no mouse movement or keyboard input in the
glass layer viewport for 3+ minutes) and returns (mouse enters viewport),
show a brief summary card centered on the glass.

**Implementation:**
- Track `lastActivityAt` timestamp via `onMouseMove` and `onKeyDown` handlers
  on the glass layer container. Use a `useRef` (not state) to avoid re-renders.
- On mouse re-entry after 3+ minutes of inactivity, compute a briefing:
  - Count of tasks completed while away
  - Count of new notifications
  - Current bridge state
- Show a `BriefingCard` component centered on the glass for 8 seconds or until
  clicked/dismissed

**BriefingCard design:**
- Glass morphism card (320px wide), centered
- "While you were away:" header in Inter 14px `#e0e0e0`
- Bullet list: "3 tasks completed", "1 new notification", "Trust stable"
- Auto-dismiss after 8 seconds (fade out 500ms)
- Click anywhere to dismiss immediately
- Only show if something actually happened (tasks completed or new notifications)

### Completion Celebrations

When a task transitions from `working`/`review` to `done`, trigger a brief
celebration effect — a department-colored bloom around the task card before it
fades from the glass.

**Implementation:**
- Track previous task statuses via `useRef<Map<string, string>>()` in GlassLayer
- On each render, compare current statuses to previous. If a task went from
  non-done to `done`, mark it for celebration
- Celebration: the task card wrapper gets a brief class/style that applies a
  radial gradient bloom in the department color (600ms, ease-out)
- After the bloom, the task fades out as normal (it's done, so it gets filtered
  out on next render)

**Bloom CSS:**
```css
@keyframes glass-celebration {
  0% { box-shadow: 0 0 0 rgba(var(--dept-color), 0); }
  40% { box-shadow: 0 0 40px rgba(var(--dept-color), 0.3); }
  100% { box-shadow: 0 0 0 rgba(var(--dept-color), 0); }
}
```

Since CSS custom properties can't take RGB tuples easily in inline styles, use
a style object with the department color directly in the animation, or define
a few keyframe variants per department (engineering, science, medical, security).

A simpler approach: apply the bloom as an inline `boxShadow` style that
transitions, toggled by a `celebrating` flag per task.

## File Plan

| Action | File | Description |
|--------|------|-------------|
| CREATE | `ui/src/components/glass/ContextRibbon.tsx` | Dense HUD strip at top edge |
| CREATE | `ui/src/components/glass/BriefingCard.tsx` | Return-to-bridge summary card |
| MODIFY | `ui/src/components/GlassLayer.tsx` | Add ContextRibbon, ambient edge glow, celebration tracking, briefing logic |
| CREATE | `ui/src/__tests__/GlassBridgeState.test.tsx` | Tests for bridge state + Context Ribbon |

## Acceptance Criteria

1. Bridge state derived correctly: idle (no active tasks), autonomous (active
   but none need attention), attention (any requires_action or action_required)
2. Context Ribbon renders at top of glass with agent count, active task count,
   attention count, system mode, and bridge state indicator
3. Ambient edge glow changes color based on bridge state (cyan→gold→amber)
4. Edge glow transitions smoothly over 1200ms when state changes
5. Briefing card appears after 3+ minutes of inactivity, summarizes changes
6. Briefing card auto-dismisses after 8 seconds or on click
7. Task completion triggers a brief department-colored bloom on the card
8. Context Ribbon only renders when glass layer is visible (canvas mode, active tasks)
9. All text in Context Ribbon uses JetBrains Mono, 10px
10. Glass layer still renders correctly with 0 tasks (even if briefly — the
    ContextRibbon should also gracefully handle the idle state as the layer
    may render for the briefing card)

## Store Changes

**No new store fields.** Everything is derived:
- Bridge state: computed from `agentTasks` + `notifications`
- Last activity: `useRef` in GlassLayer (component-local)
- Celebration tracking: `useRef<Map>` in GlassLayer
- Briefing data: computed on mouse re-entry

## Important Rendering Note

Currently GlassLayer returns `null` when there are no active tasks. For the
briefing card to show after Captain absence (even if all tasks completed while
away), the GlassLayer should render when:
- There are active tasks (existing behavior), OR
- A briefing is pending display

Use a `showBriefing` state (local `useState`, not store) to keep the layer
mounted during briefing display.

## Test Requirements

Create `ui/src/__tests__/GlassBridgeState.test.tsx`:

1. **deriveBridgeState returns 'idle'** when no tasks
2. **deriveBridgeState returns 'autonomous'** when tasks active, none need attention
3. **deriveBridgeState returns 'attention'** when any task has requires_action
4. **deriveBridgeState returns 'attention'** when notification has action_required
5. **edge glow color maps to bridge state** — verify color strings per state
6. **celebration detected on status transition** — done status after working

## Do NOT Build

- **Do NOT** add scan lines, data rain, or chromatic aberration — that is AD-391
- **Do NOT** add sound effects — that is AD-391
- **Do NOT** add trust-driven card sizing or Command Surface breathing — AD-392
- **Do NOT** add Captain's Gaze attention weighting — that is AD-392
- **Do NOT** modify CognitiveCanvas, IntentSurface, or BridgePanel
- **Do NOT** add new WebSocket events or backend endpoints
