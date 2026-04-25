# AD-392: Adaptive Bridge

## Overview

The final Glass Bridge phase. The glass learns the Captain's patterns and adapts:
trust-driven progressive reveal makes high-trust agent cards quieter while
low-trust agents stay prominent. The Command Surface (resting pill) breathes with
engagement — receding during autonomous execution, swelling on Captain proximity.
Captain's Gaze tracks mouse position to promote attended task cards. Responsive
breakpoints adapt the glass layout from ultrawide to mobile.

This is Phase 5 of the Glass Bridge. Builds on AD-388 (overlay), AD-389 (DAG),
AD-390 (ambient intelligence), AD-391 (atmosphere). Full design spec:
`docs/design/hxi-glass-bridge.md`.

## Architecture

### 1. Trust-Driven Progressive Reveal

Modify `GlassTaskCard.tsx` to accept a `trust` prop and vary its visual
presentation based on agent trust level.

**Trust bands** (matching existing `AgentTooltip.tsx` convention):
- **Low trust (<0.35):** Full-size card (280px), thicker left border (4px),
  slightly brighter background (`rgba(26, 26, 46, 0.8)`), trust indicator dot
  (purple `#7060a8`)
- **Medium trust (0.35–0.7):** Standard card (280px), normal border (3px),
  current background, trust indicator dot (blue `#88a4c8`)
- **High trust (>0.7):** Condensed card (240px), thinner border (2px), dimmer
  background (`rgba(26, 26, 46, 0.55)`), reduced padding, smaller font
  (12px title, 9px system), trust indicator dot (gold `#f0b060`). The glass
  gets quieter as the crew earns trust.

**Implementation:**
- `GlassTaskCard` gains a `trust: number` prop (default 0.5)
- In `GlassLayer.tsx`, look up trust from the store's `agents` Map using
  `task.agent_id`:
  ```tsx
  const agents = useStore(s => s.agents);
  // Inside task iteration:
  const agentTrust = agents.get(task.agent_id)?.trust ?? 0.5;
  ```
- The trust dot renders as a small circle (6px) next to the department label,
  colored by trust band
- The condensed high-trust card uses the same structure but with tighter spacing
  — no layout changes, just CSS tweaks

### 2. Command Surface Breathing

Modify `IntentSurface.tsx` to make the resting pill respond to bridge state and
Captain proximity.

**Breathing behavior:**
- **Autonomous bridge state + no mouse near pill (>200px away):** Pill recedes
  to a thin glow line — `width: 80px`, `height: 4px`, `opacity: 0.4`,
  `borderRadius: 2px`. Just a cyan glow hint at the bottom center. Text hidden.
- **Autonomous + mouse within 200px of pill:** Pill swells back to normal
  (`width: 160px`, `height: 40px`). Transition: 300ms ease-out.
- **Attention or Idle bridge state:** Pill stays at normal size (Captain is
  needed or nothing is happening — the input surface should be available).
- **Recede transition:** 800ms ease-in (slow fade-out, doesn't distract).
- **Swell transition:** 300ms ease-out (quick response to Captain engagement).

**Implementation:**
- `IntentSurface.tsx` needs to read `bridgeState` from the current state. Import
  `deriveBridgeState` and `BridgeState` from `ContextRibbon.tsx`. Read
  `agentTasks` and `notifications` from the store and derive bridge state.
- Track mouse distance to pill center using `onMouseMove` on the container div
  (the one with `position: fixed; bottom: 44`). Use a ref to store current
  mouse position and compute distance from pill center on each move.
- Add a `pillState` ref: `'normal' | 'receded'`. Recede when
  `bridgeState === 'autonomous'` AND mouse is far (>200px). Swell otherwise.
- Apply CSS transitions on `width`, `height`, `opacity`, `borderRadius` for
  smooth breathing.
- When receded, hide the text label and badge using `opacity: 0` (not
  `display: none` — needs to animate back).

### 3. Captain's Gaze — Attention-Weighted Task Promotion

Track mouse position within the glass layer and promote the task card closest to
the Captain's gaze.

**Implementation in GlassLayer.tsx:**
- Add an `onMouseMove` handler to the glass layer div that stores the current
  mouse position in a ref: `gazeRef = useRef<{x: number, y: number} | null>(null)`
- Every frame (via the existing activity tracking or a throttled interval),
  determine which task card center is closest to the gaze point
- The "gazed" task gets a subtle visual boost:
  - Slightly larger scale: `transform: scale(1.03)`
  - Slightly brighter background: increase alpha by +0.05
  - Subtle glow: `boxShadow: 0 0 12px rgba(STATE_COLOR, 0.15)`
  - Transition: 200ms ease-out (fluid, not jumpy)
- Store the gazed task id in a ref (not state — avoid re-renders on every
  mouse move). Use `requestAnimationFrame` to apply the visual effect via
  direct DOM manipulation on the task card wrapper divs (add/remove a CSS class
  or inline style).
- When mouse leaves the glass layer (`onMouseLeave`), clear the gaze ref.
- **Performance:** Throttle the distance calculation to every 100ms using a
  timestamp check inside the mousemove handler. Do NOT recalculate on every
  pixel of mouse movement.

**Alternative (simpler) approach if direct DOM manipulation is too complex:**
- Store `gazedTaskId: string | null` in a `useState` but update it only every
  100ms via a throttled callback. Pass it as a prop to `GlassTaskCard`.
- `GlassTaskCard` applies the visual boost when `isGazed` prop is true.
- This is simpler and more React-idiomatic, at the cost of 10Hz state updates.
  **Prefer this approach.**

### 4. Responsive Breakpoints

Add a `useBreakpoint()` hook and adapt the glass layout to viewport width.

**Create `ui/src/hooks/useBreakpoint.ts`:**
```tsx
import { useState, useEffect } from 'react';

export type Breakpoint = 'ultrawide' | 'standard' | 'laptop' | 'tablet' | 'mobile';

export function useBreakpoint(): Breakpoint {
  const [bp, setBp] = useState<Breakpoint>(getBreakpoint());

  useEffect(() => {
    const handler = () => setBp(getBreakpoint());
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  return bp;
}

function getBreakpoint(): Breakpoint {
  const w = window.innerWidth;
  if (w > 2560) return 'ultrawide';
  if (w > 1440) return 'standard';
  if (w > 1024) return 'laptop';
  if (w > 768) return 'tablet';
  return 'mobile';
}
```

**Responsive adjustments in GlassLayer:**
- `ultrawide` / `standard`: Current layout unchanged. Full constellation.
- `laptop`: Task cards slightly narrower (260px), ContextRibbon font reduced.
  Constellation max 3 visible at once, overflow scrollable.
- `tablet`: Vertical stack layout. ContextRibbon stays at top. Task cards stack
  vertically centered, full width (minus 32px padding). No constellation offsets.
- `mobile`: Single card fills viewport width (minus 24px padding). Only the
  highest-priority task visible at a time. Swipe gesture NOT needed (future AD).
  ContextRibbon collapses to just the state dot and attention count.

**Responsive adjustments in GlassTaskCard:**
- Accept a `compact` prop (boolean, default false). When true: narrower card,
  smaller fonts (12px title, 9px system), reduced padding.
- `GlassLayer` sets `compact={true}` on `tablet` and `mobile` breakpoints.

**Responsive adjustments in ContextRibbon:**
- Accept a `compact` prop. When true: hide label and system mode text, show
  only state dot + agent count + attention count.

## File Plan

| Action | File | Description |
|--------|------|-------------|
| CREATE | `ui/src/hooks/useBreakpoint.ts` | Viewport breakpoint detection hook |
| MODIFY | `ui/src/components/glass/GlassTaskCard.tsx` | Trust-driven visual variants + compact prop + isGazed prop |
| MODIFY | `ui/src/components/glass/ContextRibbon.tsx` | Compact prop for responsive |
| MODIFY | `ui/src/components/GlassLayer.tsx` | Captain's Gaze tracking, trust lookup, responsive layout, breakpoint integration |
| MODIFY | `ui/src/components/IntentSurface.tsx` | Command Surface breathing (recede/swell) |
| CREATE | `ui/src/__tests__/GlassAdaptive.test.tsx` | Tests for trust bands, breakpoints, breathing logic |

## Acceptance Criteria

1. Low-trust agent task cards are visually prominent (brighter, thicker border)
2. High-trust agent task cards are condensed (smaller, dimmer, thinner border)
3. Trust dot (6px) appears on each task card colored by trust band
4. Resting pill recedes to thin glow line during autonomous bridge state when mouse is far
5. Resting pill swells back on mouse proximity (200px threshold) or non-autonomous state
6. Recede transition is 800ms ease-in, swell is 300ms ease-out
7. Captain's Gaze: task nearest to mouse gets subtle scale(1.03) + glow boost
8. Gaze tracking is throttled to 100ms intervals (no per-pixel updates)
9. `useBreakpoint()` returns correct breakpoint for all 5 viewport ranges
10. Task cards use compact layout on tablet/mobile breakpoints
11. ContextRibbon collapses on mobile to dot + counts only
12. Glass layer still renders correctly at standard desktop width (zero regression)
13. All effects degrade gracefully — no JavaScript errors on any viewport width

## Test Requirements

Create `ui/src/__tests__/GlassAdaptive.test.tsx`:

1. **Trust band thresholds** — verify trust < 0.35 = low, 0.35-0.7 = medium, > 0.7 = high
2. **Trust color mapping** — low = `#7060a8`, medium = `#88a4c8`, high = `#f0b060`
3. **Condensed card dimensions** — high-trust card width is 240px (vs 280px standard)
4. **Breakpoint detection** — test `getBreakpoint()` with mocked `window.innerWidth` for all 5 ranges
5. **Pill breathing logic** — autonomous + far mouse → receded; attention → normal; autonomous + near mouse → normal
6. **Gaze throttle** — verify gaze only updates every 100ms (test the throttle logic)

## Do NOT Build

- **Do NOT** add WebSocket messages or backend endpoints — all AD-392 logic is
  frontend-only. Captain's Gaze affects visual emphasis, not actual agent
  priority (that would require backend changes for a future AD).
- **Do NOT** add swipe gestures on mobile — future enhancement
- **Do NOT** modify CognitiveCanvas or BridgePanel
- **Do NOT** add new store fields for gaze position — use refs, not Zustand state
- **Do NOT** use emoji anywhere in the UI
- **Do NOT** implement side zones (Zones 2 and 4 from the design spec) — the
  current glass only has Zone 1 (ContextRibbon) and Zone 3 (task center).
  Side zones are a future enhancement.
