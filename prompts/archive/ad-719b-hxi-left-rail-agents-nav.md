# AD-719b — Copilot-style left rail + Agents nav

**Status:** Draft for Wave 163
**Dependencies:** AD-719 ✅ (Wave 135, multi-agent chat fan-out), existing IntentSurface shell.
**Closes:** #547
**Estimated tests:** 5 Vitest
**Build order:** Independent of the peer-observation cluster.

## Problem

The current HXI shell is a single-bloom IntentSurface. Issue #513 sketched three mental models; AD-719b ships Mental Model (c): a Copilot-style left rail with recent agents/conversations + an Agents nav surface. This is a UI shell refactor, not a feature.

## Scope discipline

This AD ADDS the left rail as a NEW shell component. It does NOT remove the existing IntentSurface — the two coexist. The left rail is opt-in via a new HXI setting `hxi_left_rail_enabled` (localStorage key, default False for v1; flip to True in a later AD once Captain has lived with it).

## Section 0: Component layout

New components under `ui/src/hxi/leftrail/`:

- `LeftRail.tsx` — top-level container, fixed-width (240px on wide screens, collapsible to 56px icon-only). Mounts at the App root next to IntentSurface.
- `LeftRailAgentsSection.tsx` — list of online agents grouped by department. Click → focuses the agent panel / opens a DM.
- `LeftRailRecentSection.tsx` — recent WardRoom threads + recent DMs. Click → navigates the active surface.
- `LeftRailNavButton.tsx` — small icon button for "Agents" / "WardRoom" / "Knowledge" nav.

All icons inline SVG stroke-based per HXI Design Principle #3. Active state amber `#f0b060`, inactive `#666680`.

## Section 1: State management

Reuse existing stores (`useStore` zustand-style — verify exact pattern):

- `useFleetAvatarTelemetry` for online-agent list (already exists per Wave 163 file-listing).
- WardRoom thread list source — verify the existing source by reading `WardRoomThreadList.tsx`.
- DM recency — verify whether a "recent DMs" source exists; if not, derive from the existing WardRoom thread store filtered by DM flag.

NO new global store. NO new context provider. The left rail is a pure consumer of existing state.

## Section 2: HXI setting

New localStorage key `hxi_left_rail_enabled`. Default False. Flip via a small toggle in the existing Profile/Settings panel (verify location: likely `ProfileInfoTab.tsx` or a sibling). When False, `LeftRail.tsx` returns null.

## Section 3: Collapsed vs expanded

Two states:
- **Expanded (240px)** — full labels visible, agent names, thread titles.
- **Collapsed (56px)** — icon-only, names on hover via existing tooltip pattern.

Persistent state in localStorage `hxi_left_rail_collapsed`.

## Section 4: Accessibility / progressive disclosure

Per HXI Design Principle #5, show less by default:
- First-time users see expanded state with limited density (max 5 agents, max 3 recent threads).
- A "Show more" affordance expands the list.
- Veteran users (visit count >10) see denser display (max 12 agents, max 8 threads).

Visit count tracked in localStorage `hxi_visit_count`.

## Section 5: Tests (≥5 Vitest)

`ui/src/hxi/leftrail/LeftRail.test.tsx`:

1. `hxi_left_rail_enabled=false` (default) → component renders null.
2. `hxi_left_rail_enabled=true` → component renders with agents section + recent section.
3. Click agent → existing focus-agent action triggered (mock the store action).
4. Click recent thread → existing navigate-to-thread action triggered.
5. Collapse toggle: clicking the toggle persists `hxi_left_rail_collapsed=true` to localStorage AND the rendered width adjusts.

## Section 6: Builder Standing Rules

- BF-274: single replace for adjacent edits.
- BF-280: n/a (UI).
- BF-282: n/a (UI).
- BF-286: test scaffolding mirrors production component shape.
- BF-287: no MagicMock at the store boundary — use `vi.mock` of the store hooks.
- **AD-738b: REQUIRED `npm run build` GATE** — this AD heavily touches `ui/src/`. Per-commit gate MUST run BOTH `npx vitest run` AND `npm run build`.
- AD-731 invariant: n/a.
- HXI Design Principle #3: inline SVG glyphs only.
- HXI Design Principle #5: progressive disclosure.
- HXI Design Principle #8: bootstrap-tier UI — fixed for v1; later ADs can make it more generative.

## What this does NOT change

- The existing IntentSurface — coexists with the left rail.
- The existing WardRoom / Knowledge / Profile panels.
- Any backend / API.
- Any agent behavior.

## Tracking

- `PROGRESS.md`: CLOSED entry referencing #547.
- `docs/development/roadmap.md`: move AD-719b from forward markers; AD-719b-2 forward marker filed for default-flip.
- `DECISIONS.md`: append AD-719b entry — left rail shell shipped default-OFF.

## Forward markers (TECHNICAL triggers per AD-722c-3)

- **AD-719b-2 — `hxi_left_rail_enabled` default True.** Trigger: when Captain has used the left rail across ≥5 sessions (visit count ≥5 AND localStorage shows non-null collapsed state). Issue filed.

## Acceptance Criteria

1. All Section 0-4 deliverables landed.
2. ≥5 Vitest tests pass: `cd ui ; npx vitest run` green.
3. **`cd ui ; npm run build` green** (BF-279 / AD-738b).
4. Default rendering with `hxi_left_rail_enabled=false` produces NO visible UI change (zero-regression for existing users).
5. No emoji; inline SVG glyphs only.
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-15)

```
ls ui/src/wardroom/
  WardRoomChannelList.tsx, WardRoomPanel.tsx, WardRoomThreadDetail.tsx, WardRoomThreadList.tsx
  (existing surfaces — left rail consumes their store)

ls ui/src/avatars/useFleetAvatarTelemetry.ts
  (online-agent telemetry already exists)
```

**Builder verify-first flags:**
- Existing Profile/Settings toggle location for the new `hxi_left_rail_enabled` flag — VERIFY.
- Zustand store hooks for online-agents + WardRoom threads — VERIFY exact names.
- Navigation action API used by existing nav-style components — VERIFY before Section 1 wiring.
