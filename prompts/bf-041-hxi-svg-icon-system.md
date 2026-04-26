# BF-041: HXI Icon System — SVG Glyph Cleanup

**Status:** Ready for builder
**Priority:** Medium
**Files:** `ui/src/components/icons/Glyphs.tsx`, `ui/src/components/icons/Glyphs.test.tsx`, plus 13 component files listed below

## Problem

HXI icon system diverges from the canonical SVG-only design language defined in `.github/copilot-instructions.md` (HXI Design Principle #3):

> "No emoji in the UI. All icons are inline SVG with `strokeWidth: 1.5`, `strokeLinecap: round`. Active state: amber (`#f0b060`). Inactive: dim (`#666680`). Glow on hover via `drop-shadow`. Emoji break the immersion."

Multiple components use Unicode text glyphs (`▶`, `▼`, `✕`, `◆`, `●`, `⚠`, `←`, `→`, `💬`, etc.) instead of stroke-based SVG icons. These render inconsistently across browsers/platforms and break the bioluminescent design language.

## What This Does

1. Creates a shared SVG glyph component library at `ui/src/components/icons/Glyphs.tsx`
2. Replaces every Unicode glyph across all HXI surfaces with the corresponding SVG component
3. Adds vitest tests verifying each glyph renders correctly

## What This Does NOT Change

- No functional behavior changes — every glyph replacement is purely visual
- No new dependencies
- No changes to store, types, API, or Python backend
- No layout or spacing changes beyond what's needed to swap text for inline SVG
- The `·` (middle dot / `\u00B7`) separator used between metadata fields is retained as-is — it's a typographic separator, not an icon glyph. Same for `…` (ellipsis / `\u2026`) text truncation and `' → '` text connectors in BillDashboard.

---

## Section 1: Create Shared SVG Glyph Library

**File:** `ui/src/components/icons/Glyphs.tsx` (NEW)

Create this file with named React component exports. Every glyph is an inline `<svg>` element with these shared properties:

```tsx
// Shared SVG defaults per HXI Design Principle #3
const defaultProps = {
  xmlns: 'http://www.w3.org/2000/svg',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
};
```

Each component accepts an optional `size` prop (default 12) and optional `className` / `style` props for per-use customization. Every component uses `display: 'inline-block'` and `verticalAlign: 'middle'` by default so they drop in where text glyphs currently sit.

### Required Glyphs

Define and export these named components:

| Component | Replaces | SVG Path Description |
|-----------|----------|---------------------|
| `ChevronDown` | `▼`, `▾`, `\u25BC` | Downward chevron: `M4 6 L8 10 L12 6` (viewBox 0 0 16 16) |
| `ChevronRight` | `▶`, `▸`, `\u25B6` | Right chevron: `M6 4 L10 8 L6 12` (viewBox 0 0 16 16) |
| `ChevronUp` | `▴` | Upward chevron: `M4 10 L8 6 L12 10` (viewBox 0 0 16 16) |
| `ArrowLeft` | `←` | Left arrow: `M10 4 L4 8 L10 12` with `M4 8 H13` (viewBox 0 0 16 16) |
| `ArrowRight` | `→` | Right arrow: `M6 4 L12 8 L6 12` with `M3 8 H12` (viewBox 0 0 16 16) |
| `ArrowUp` | `▲` | Upward arrow: `M4 10 L8 4 L12 10` with `M8 4 V13` (viewBox 0 0 16 16) |
| `Close` | `✕`, `×`, `\u00D7` | X mark: `M4 4 L12 12 M12 4 L4 12` (viewBox 0 0 16 16) |
| `Warning` | `⚠`, `\u26A0`, `&#9888;` | Triangle with exclamation: `M8 3 L14 13 H2 Z` (stroke) + `M8 7 V9 M8 11 V11.5` (viewBox 0 0 16 16) |
| `StatusDone` | `●`, `\u25CF` (done step) | Filled circle: `<circle cx="8" cy="8" r="4" fill="currentColor" stroke="none" />` (viewBox 0 0 16 16) |
| `StatusPending` | `○`, `\u25CB` (pending step) | Open circle: `<circle cx="8" cy="8" r="4" />` (viewBox 0 0 16 16) |
| `StatusInProgress` | `◐`, `\u25D0` (in_progress step) | Half-filled circle: `<circle cx="8" cy="8" r="4" />` + `<path d="M8 4 A4 4 0 0 0 8 12 Z" fill="currentColor" />` (viewBox 0 0 16 16) |
| `StatusFailed` | `✕`, `\u2715` (failed step) | X in circle: `<circle cx="8" cy="8" r="5" />` + `M6 6 L10 10 M10 6 L6 10` (viewBox 0 0 16 16) |
| `Expand` | `↗`, `\u2197` | Diagonal arrow: `M6 4 H12 V10` + `M12 4 L4 12` (viewBox 0 0 16 16) |
| `Diamond` | `◈`, `\u25C8` (DAG progress) | Diamond: `M8 2 L14 8 L8 14 L2 8 Z` (viewBox 0 0 16 16) |
| `DiamondOpen` | `◇`, `\u25C7` | Open diamond: same as Diamond, no fill |
| `Bullseye` | `◎`, `\u25CE` | Concentric circles: `<circle cx="8" cy="8" r="5" />` + `<circle cx="8" cy="8" r="2" />` (viewBox 0 0 16 16) |
| `Check` | `✓`, `\u2713` | Checkmark: `M3 8 L6 11 L13 4` (viewBox 0 0 16 16) |
| `XMark` | `✗`, `\u2717` | X mark (heavier): `M4 4 L12 12 M12 4 L4 12` (viewBox 0 0 16 16) |
| `Sparkle` | `✦`, `\u2726` (resting pill) | 4-point star: `M8 2 L9.5 6.5 L14 8 L9.5 9.5 L8 14 L6.5 9.5 L2 8 L6.5 6.5 Z` (viewBox 0 0 16 16) |
| `PlayArrow` | `▶` (game turn) | Right-pointing triangle: `M5 3 L13 8 L5 13 Z` (viewBox 0 0 16 16) |
| `Lock` | `🔒`, `\u{1F512}` | Padlock closed: rect body + arc shackle (viewBox 0 0 16 16) — `M5 8 H11 V13 H5 Z` (body) + `M6 8 V6 A2 2 0 0 1 10 6 V8` (shackle) |
| `Unlock` | `🔓`, `\u{1F513}` | Padlock open: same body + open shackle — `M5 8 H11 V13 H5 Z` + `M6 8 V6 A2 2 0 0 1 10 6` (shackle lifted) |
| `Comment` | `💬` | Speech bubble: rounded rect with tail — `M3 3 H13 Q14 3 14 4 V10 Q14 11 13 11 H6 L3 14 V4 Q3 3 4 3 Z` (viewBox 0 0 16 16) |

**Important:** The `StatusDone` glyph uses `fill="currentColor"` and `stroke="none"` — it's the ONE exception to the stroke-only rule because it represents a "filled" completed state, which is semantically correct and matches the original `●`.

---

## Section 2: Replace Unicode Glyphs — File-by-File

Add `import { ... } from '../icons/Glyphs';` (or `'../../icons/Glyphs'` for nested components) at the top of each file. Replace each Unicode glyph as specified.

### 2a: `ui/src/components/BridgePanel.tsx`

**Import path:** `'./icons/Glyphs'`

| Line | Current | Replacement |
|------|---------|-------------|
| 36 | `{open ? '\u25BC' : '\u25B6'}` | `{open ? <ChevronDown size={8} /> : <ChevronRight size={8} />}` |
| 52 | `{'\u2197'}` | `<Expand size={10} />` |
| 161 | `{'\u00D7'}` | `<Close size={14} />` |

### 2b: `ui/src/components/bridge/BridgeCards.tsx`

**Import path:** `'../../icons/Glyphs'`

| Line | Current | Replacement |
|------|---------|-------------|
| 22–27 | `STEP_ICONS` object with `'\u25CB'`, `'\u25D0'`, `'\u25CF'`, `'\u2715'` strings | Replace the entire `STEP_ICONS` pattern — see below |

The `STEP_ICONS` map currently returns strings that are rendered as text content. Replace the rendering pattern in `StepList` (line 56):

Current:
```tsx
<span style={{ color: STATUS_COLORS[step.status] || '#888' }}>
  {STEP_ICONS[step.status] || '\u25CB'}
</span>
```

Replace the `STEP_ICONS` map with a component map:
```tsx
import { StatusDone, StatusInProgress, StatusPending, StatusFailed } from '../../icons/Glyphs';

const STEP_ICON_COMPONENTS: Record<string, React.FC<{ size?: number }>> = {
  pending: StatusPending,
  in_progress: StatusInProgress,
  done: StatusDone,
  failed: StatusFailed,
};
```

And the rendering:
```tsx
<span style={{ color: STATUS_COLORS[step.status] || '#888' }}>
  {(() => {
    const Icon = STEP_ICON_COMPONENTS[step.status] || StatusPending;
    return <Icon size={10} />;
  })()}
</span>
```

Also replace the `'\u00B7'` middle-dot separators in `TaskCard` (lines 137, 141):

| Line | Current | Replacement |
|------|---------|-------------|
| 137 | `{'\u00B7'}` | Keep as-is — typographic separator, not icon |
| 141 | `{'\u00B7'}` | Keep as-is — typographic separator, not icon |

**Decision:** The `·` middle-dot is a text separator, not a glyph/icon. It stays as text. Same applies across all components.

### 2c: `ui/src/components/bridge/BridgeNotifications.tsx`

No Unicode glyphs to replace beyond `·` separators. No changes needed.

### 2d: `ui/src/components/bridge/BridgeSystem.tsx`

**Import path:** `'../../icons/Glyphs'`

| Line | Current | Replacement |
|------|---------|-------------|
| 177 | `{t.locked ? '\u{1F512}' : '\u{1F513}'}` | `{t.locked ? <Lock size={11} /> : <Unlock size={11} />}` |

### 2e: `ui/src/components/glass/GlassDAGNodes.tsx`

**Import path:** `'../../icons/Glyphs'`

Same pattern as BridgeCards: replace the `STEP_ICONS` string map (lines 13–18) with a component map and update the rendering on line 157:

Current:
```tsx
{STEP_ICONS[step.status] || '\u25CB'}
```

Replace with:
```tsx
{(() => {
  const Icon = STEP_ICON_COMPONENTS[step.status] || StatusPending;
  return <Icon size={14} />;
})()}
```

Import the same `StatusDone, StatusInProgress, StatusPending, StatusFailed` components and define the same `STEP_ICON_COMPONENTS` map. Remove the old `STEP_ICONS` string map.

### 2f: `ui/src/components/glass/ContextRibbon.tsx`

No Unicode glyphs to replace beyond the `·` separator (line 40). No changes needed.

### 2g: `ui/src/components/AgentTooltip.tsx`

**Import path:** `'./icons/Glyphs'`

| Line | Current | Replacement |
|------|---------|-------------|
| 106 | `{'\u00B7'}` | Keep as-is — separator |
| 141 | `{'\u26A0'} Needs attention` | `<Warning size={10} /> Needs attention` |

### 2h: `ui/src/components/GamePanel.tsx`

**Import path:** `'./icons/Glyphs'`

| Line | Current | Replacement |
|------|---------|-------------|
| 124 | `>✕</button>` | `><Close size={14} /></button>` |
| 126 | `>✕</button>` | `><Close size={14} /></button>` |
| 142 | `'▶ Your turn'` | `<><PlayArrow size={12} /> Your turn</>` |

### 2i: `ui/src/components/wardroom/WardRoomPanel.tsx`

**Import path:** `'../../icons/Glyphs'`

| Line | Current | Replacement |
|------|---------|-------------|
| 91 | `View conversation →` | `View conversation <ArrowRight size={10} />` |
| 157 | `>←</span>` | `><ArrowLeft size={14} /></span>` |
| 168 | `>✕</span>` | `><Close size={16} /></span>` |
| 200 | `>←</span>` | `><ArrowLeft size={14} /></span>` |

### 2j: `ui/src/components/wardroom/WardRoomThreadList.tsx`

**Import path:** `'../../icons/Glyphs'`

| Line | Current | Replacement |
|------|---------|-------------|
| 66 | `<span>▲ {t.net_score}</span>` | `<span><ArrowUp size={10} /> {t.net_score}</span>` |
| 67 | `<span>💬 {t.reply_count}</span>` | `<span><Comment size={10} /> {t.reply_count}</span>` |

### 2k: `ui/src/components/work/WorkBoard.tsx`

**Import path:** `'../icons/Glyphs'`

| Line | Current | Replacement |
|------|---------|-------------|
| 354 | `Filters {showFilters ? '▴' : '▾'}` | `Filters {showFilters ? <ChevronUp size={8} /> : <ChevronDown size={8} />}` |
| 373 | `&#9888; {wipWarning}` | `<Warning size={10} /> {wipWarning}` |
| 522 | `<span style={{ fontSize: 8 }}>{showBlocked ? '▼' : '▶'}</span>` | `<span>{showBlocked ? <ChevronDown size={8} /> : <ChevronRight size={8} />}</span>` |

### 2l: `ui/src/components/profile/ProfileWorkTab.tsx`

**Import path:** `'../../icons/Glyphs'`

| Line | Current | Replacement |
|------|---------|-------------|
| 124 | `<span style={{ fontSize: 8 }}>{sectionsOpen[key] ? '▼' : '▶'}</span>` | `<span>{sectionsOpen[key] ? <ChevronDown size={8} /> : <ChevronRight size={8} />}</span>` |

### 2m: `ui/src/components/profile/MemoryGraph3D.tsx`

**Import path:** `'../../icons/Glyphs'`

| Line | Current | Replacement |
|------|---------|-------------|
| 141 | `>×</button>` | `><Close size={14} /></button>` |

### 2n: `ui/src/components/IntentSurface.tsx`

**Import path:** `'./icons/Glyphs'`

| Line | Current | Replacement |
|------|---------|-------------|
| 139 | `\u25C8 ${done}/${activeDag.length} tasks` | Use template literal: `` `${done}/${activeDag.length} tasks` `` with `<Diamond size={10} />` prepended before the text in JSX, not inside the string. Refactor `dagText` from string to JSX. |
| 240 | `'\u2713 Learned'` / `'\u2713 Noted'` | Replace with JSX: `<><Check size={10} /> Learned</>` / `<><Check size={10} /> Noted</>` — this requires `confirmLabel` to be `ReactNode` not `string`. Refactor the `confirmLabel` variable type. |
| 267 | `'\u2717 Failed'` | `<><XMark size={10} /> Failed</>` — same refactor, `confirmText` to `ReactNode`. |
| 580 | `'\u25CB Enriching...'` / `'\u25C7 Enrich Spec'` | `<><StatusPending size={10} /> Enriching...</>` / `<><DiamondOpen size={10} /> Enrich Spec</>` |
| 605 | `{'\u25CE'} Enriched Agent Spec:` | `<Bullseye size={12} /> Enriched Agent Spec:` |
| 650 | `{'\u25C7'} Edit` | `<DiamondOpen size={10} /> Edit` |
| 709 | `'\u25BC Hide Code'` / `'\u25B6 View Code'` | `<><ChevronDown size={10} /> Hide Code</>` / `<><ChevronRight size={10} /> View Code</>` |
| 842 | `'\u25BC Hide Error Output'` / `'\u25B6 View Error Output'` | `<><ChevronDown size={10} /> Hide Error Output</>` / `<><ChevronRight size={10} /> View Error Output</>` |
| 970 | `{'\u26A0'} {r}` | `<Warning size={10} /> {r}` |
| 1001 | `'\u25BC Hide Full Spec'` / `'\u25B6 View Full Spec'` | `<><ChevronDown size={10} /> Hide Full Spec</>` / `<><ChevronRight size={10} /> View Full Spec</>` |
| 1586 | `{'\u2726'}` | `<Sparkle size={14} />` |

**Note on IntentSurface refactoring:** Some replacements change string values to JSX. Where a variable is typed as `string` but now holds JSX, update the type to `ReactNode` and ensure the rendering location supports JSX (it will — these are all rendered in JSX context already). The `feedbackMap` type uses `confirmText: string` — update `FeedbackStatus` to `confirmText: React.ReactNode`.

---

## Section 3: Tests

**File:** `ui/src/components/icons/Glyphs.test.tsx` (NEW)

Use Vitest + `@testing-library/react`. Test each glyph component renders correctly.

**Imports:**
```tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import * as Glyphs from './Glyphs';
```

### Test 1: `each glyph renders an SVG element`

Use `Object.entries(Glyphs)` to iterate all exports. For each, render it and assert an `<svg>` element is present in the container.

```tsx
const glyphNames = Object.keys(Glyphs).filter(
  k => typeof (Glyphs as any)[k] === 'function'
);

describe.each(glyphNames)('%s', (name) => {
  it('renders an SVG element', () => {
    const Component = (Glyphs as any)[name];
    const { container } = render(<Component />);
    expect(container.querySelector('svg')).toBeTruthy();
  });

  it('applies default stroke properties', () => {
    const Component = (Glyphs as any)[name];
    const { container } = render(<Component />);
    const svg = container.querySelector('svg');
    // StatusDone uses fill, not stroke — skip stroke check for it
    if (name !== 'StatusDone') {
      expect(svg?.getAttribute('stroke')).toBe('currentColor');
      expect(svg?.getAttribute('stroke-width')).toBe('1.5');
      expect(svg?.getAttribute('stroke-linecap')).toBe('round');
    }
  });

  it('respects custom size prop', () => {
    const Component = (Glyphs as any)[name];
    const { container } = render(<Component size={24} />);
    const svg = container.querySelector('svg');
    expect(svg?.getAttribute('width')).toBe('24');
    expect(svg?.getAttribute('height')).toBe('24');
  });
});
```

### Test 2: `StatusDone uses fill instead of stroke`

```tsx
it('StatusDone uses fill=currentColor', () => {
  const { container } = render(<Glyphs.StatusDone />);
  const circle = container.querySelector('circle');
  expect(circle?.getAttribute('fill')).toBe('currentColor');
});
```

### Test 3: `glyph count matches expected`

```tsx
it('exports the expected number of glyph components', () => {
  const count = Object.keys(Glyphs).filter(
    k => typeof (Glyphs as any)[k] === 'function'
  ).length;
  // 21 glyphs defined in BF-041
  expect(count).toBeGreaterThanOrEqual(21);
});
```

---

## Section 4: Update Existing Test

**File:** `ui/src/__tests__/ComponentRendering.test.tsx`

This test imports components and renders them. Verify it still passes after the glyph swap. No changes should be needed unless the test asserts specific text content that was a Unicode glyph. If so, update the assertion to check for SVG presence instead of text content.

---

## Verification

Run UI tests:
```
cd d:/ProbOS/ui && npx vitest run
```

Report test count.

Run the full Python test suite to confirm no backend regressions:
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

Report test count.

---

## Audit Checklist

After all replacements, the builder MUST verify NO Unicode glyphs remain by searching for these patterns across `ui/src/**/*.tsx`:

1. **Arrows/Chevrons:** `▶`, `▸`, `▾`, `▴`, `▼`, `▲`, `◀`, `◁`, `→`, `←`, `↑`, `↓`, `\u25B6`, `\u25BC`, `\u25B2`
2. **Shapes:** `●`, `○`, `◆`, `◇`, `◈`, `◐`, `◎`, `⬤`, `\u25CF`, `\u25CB`, `\u25D0`, `\u25C8`, `\u25C7`, `\u25CE`
3. **Marks:** `✕`, `✗`, `✖`, `×`, `✓`, `✦`, `\u2715`, `\u2717`, `\u2713`, `\u2726`, `\u00D7`
4. **Symbols:** `⚠`, `\u26A0`, `&#9888;`, `\u2197`
5. **Emoji:** `🔒`, `🔓`, `💬`, `\u{1F512}`, `\u{1F513}`

**Exceptions allowed (NOT glyphs, kept as text):**
- `·` / `\u00B7` — typographic middle-dot separator
- `…` / `\u2026` — text ellipsis truncation
- `' → '` — text arrow in BillDashboard role assignments (this is body text content, not a UI icon)
- `•` in regex pattern `.replace(/[-•]\s/g, '')` in IntentSurface (text processing, not rendering)

If any non-excepted glyph is found, replace it with the appropriate SVG component.

---

## Tracker Updates

### PROGRESS.md
Update BF-041 status from `Open` to `**Closed**`.

### docs/development/roadmap.md
Update BF-041 row with fix description:
```
| BF-041 | **HXI SVG icon system cleanup.** Replaced all Unicode text glyphs (▶, ▼, ✕, ●, ⚠, ←, 💬, 🔒 etc.) across 13 HXI components with stroke-based SVG components from a shared `Glyphs.tsx` library. 21 named SVG glyph components (ChevronDown, ChevronRight, Close, Warning, StatusDone, StatusPending, StatusInProgress, StatusFailed, ArrowLeft, ArrowRight, ArrowUp, Lock, Unlock, Comment, Diamond, DiamondOpen, Bullseye, Check, XMark, Sparkle, PlayArrow, Expand, ChevronUp). All glyphs use `strokeWidth: 1.5`, `strokeLinecap: round`, `currentColor` per HXI Design Principle #3. Typographic separators (`·`, `…`) retained as text. | Medium | **Closed** |
```

### DECISIONS.md
Add entry:
```
**BF-041: SVG glyph library replaces all Unicode text glyphs in HXI.** Created shared `ui/src/components/icons/Glyphs.tsx` with 21+ named SVG components. Every Unicode glyph (▶, ▼, ✕, ●, ⚠, ←, 🔒, 💬, ✦, etc.) across 13 HXI component files replaced with inline SVG using `strokeWidth: 1.5`, `strokeLinecap: round`, `currentColor`. Typographic separators (`·` middle-dot, `…` ellipsis, `→` text connector) retained as text — they are body content, not icon glyphs. The `StatusDone` circle uses `fill="currentColor"` as the one exception to stroke-only, since a filled circle semantically represents "completed." Cross-browser rendering is now consistent. Design language fully aligned with HXI Design Principle #3 from copilot-instructions.md.
```
