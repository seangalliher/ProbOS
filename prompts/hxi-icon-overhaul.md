# HXI Icon Overhaul — Bioluminescent SVG Glyphs + Neural Pulse Indicator

## Design Language

**Principle:** "Organic but digitally authentic." Every icon should look like it belongs on an interface designed by a bioluminescent civilization — not clipart, not emojis, not Material Design. Geometric primitives (circles, arcs, hexagons, chevrons) rendered with the ProbOS amber/blue/violet glow palette.

**Color palette reference (from scene.ts):**
- Amber (trust/warm): `#f0b060`
- Cool blue (neutral): `#88a4c8`
- Violet (low trust): `#7060a8`
- Green (active/healthy): `#80c878`
- Red (error/warning): `#c84858`
- Dim (inactive): `#666680`

**Icon style:**
- Inline SVG (not emoji, not icon font)
- 14-16px viewport, stroke-based (no fills — outlines only)
- strokeWidth: 1.5, strokeLinecap: "round", strokeLinejoin: "round"
- Color matches the element's semantic meaning
- Glow effect via filter: `drop-shadow(0 0 2px currentColor)` on hover/active

## Part 1: Neural Pulse Processing Indicator

In `ui/src/components/IntentSurface.tsx`, when `pendingRequests > 0`, show an animated indicator at the bottom of the chat thread:

```tsx
{pendingRequests > 0 && (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 8,
    padding: '12px 20px',
  }}>
    <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
      {[0, 1, 2].map((i) => (
        <div key={i} style={{
          width: 6, height: 6, borderRadius: '50%',
          background: 'linear-gradient(135deg, #f0b060, #88a4c8)',
          animation: `neural-pulse 1.4s ease-in-out ${i * 0.2}s infinite`,
        }} />
      ))}
    </div>
    <span style={{
      color: 'rgba(240, 176, 96, 0.5)',
      fontSize: 12, fontFamily: "'Inter', sans-serif",
      letterSpacing: '0.5px',
      animation: 'neural-pulse 2s ease-in-out infinite',
    }}>
      thinking
    </span>
  </div>
)}
```

Add to the existing `<style>` tag:
```css
@keyframes neural-pulse {
  0%, 100% { opacity: 0.2; transform: scale(0.8); }
  50% { opacity: 1.0; transform: scale(1.2); }
}
```

Place this inside the chat thread container, AFTER the message list but BEFORE the input area. The auto-scroll should bring it into view.

## Part 2: SVG Icon Replacements

### Helper: Create a small SVG icon component inline

Each icon is a small inline SVG. Create them as arrow functions or just inline JSX. Keep each one self-contained — no separate component file.

### DecisionSurface.tsx replacements:

**Sound toggle** — replace `🔊` / `🔇`:

Active (sound on) — three concentric arcs emanating from a dot:
```tsx
<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#f0b060" strokeWidth="1.5" strokeLinecap="round">
  <path d="M2 6v4l3 3h1V3H5L2 6z" />
  <path d="M9 5.5c.7.7 1 1.5 1 2.5s-.3 1.8-1 2.5" />
  <path d="M11 3.5c1.2 1.2 2 2.7 2 4.5s-.8 3.3-2 4.5" />
</svg>
```

Muted (sound off) — speaker with slash:
```tsx
<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#666680" strokeWidth="1.5" strokeLinecap="round">
  <path d="M2 6v4l3 3h1V3H5L2 6z" />
  <path d="M14 5l-5 6" />
</svg>
```

**Voice toggle** — replace `🗣️`:

Active — three vertical bars (waveform):
```tsx
<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#f0b060" strokeWidth="1.5" strokeLinecap="round">
  <line x1="4" y1="5" x2="4" y2="11" />
  <line x1="8" y1="3" x2="8" y2="13" />
  <line x1="12" y1="6" x2="12" y2="10" />
</svg>
```

Inactive:
```tsx
<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#666680" strokeWidth="1.5" strokeLinecap="round">
  <line x1="4" y1="5" x2="4" y2="11" />
  <line x1="8" y1="3" x2="8" y2="13" />
  <line x1="12" y1="6" x2="12" y2="10" />
</svg>
```

**Legend toggle** — replace `?`:

Small ring with inner dot (like a mesh node):
```tsx
<svg width="14" height="14" viewBox="0 0 16 16" fill="none" strokeWidth="1.5">
  <circle cx="8" cy="8" r="5" stroke={showLegend ? '#f0b060' : '#666680'} />
  <circle cx="8" cy="8" r="1.5" fill={showLegend ? '#f0b060' : '#666680'} />
</svg>
```

### IntentSurface.tsx replacements:

**Feedback buttons** — replace 👍 👎 ✏️:

Approve (was 👍) — upward chevron:
```tsx
<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
  <polyline points="4,10 8,5 12,10" />
</svg>
```

Reject (was 👎) — downward chevron:
```tsx
<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
  <polyline points="4,6 8,11 12,6" />
</svg>
```

Correct (was ✏️) — diamond/rhombus:
```tsx
<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
  <polygon points="8,2 14,8 8,14 2,8" />
</svg>
```

**Build Agent button** — replace `✨ Build Agent`:

Hexagon outline (crystallization):
```tsx
<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" style={{ marginRight: 6 }}>
  <polygon points="8,1 14,4.5 14,11.5 8,15 2,11.5 2,4.5" />
</svg>
Build Agent
```

**Design Agent button** — replace `🎨 Design Agent`:

Double helix / spiral (evolution):
```tsx
<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
  <path d="M4 2c0 4 8 4 8 8s-8 4-8 8" />
  <path d="M12 2c0 4-8 4-8 8s8 4 8 8" />
</svg>
Design Agent
```

**Clear chat button** — replace `🗑`:

Fade-out circle:
```tsx
<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
  <circle cx="8" cy="8" r="6" opacity="0.5" />
  <line x1="5" y1="5" x2="11" y2="11" />
  <line x1="11" y1="5" x2="5" y2="11" />
</svg>
```

**Progress step emojis** — in `api.py` (Python side), replace the emoji prefixes in the self-mod progress events:

In `src/probos/api.py`, find the `step_labels` dict in `_on_progress`:
```python
step_labels = {
    "designing": "⬡ Designing agent code...",       # hexagon
    "validating": "◎ Validating & security scan...", # target circle
    "testing": "△ Sandbox testing...",               # triangle
    "deploying": "◈ Deploying to mesh...",           # diamond in square
}
```

And the executing step:
```python
"step_label": "⚬ Executing your request...",       # small circle
```

These are Unicode geometric symbols that feel more "alien interface" than emoji. The font will render them as clean glyphs.

**Deployed indicator** — in `api.py`, change:
```python
deploy_msg = f"\u2b22 {record.class_name} deployed!"  # ⬢ hexagon (filled)
```
(was `✅`)

## Files to touch

| File | Changes |
|------|---------|
| `ui/src/components/IntentSurface.tsx` | Neural pulse indicator, feedback SVG icons, Build/Design Agent SVG icons, clear button SVG, `@keyframes neural-pulse` |
| `ui/src/components/DecisionSurface.tsx` | Sound/voice/legend SVG icons |
| `src/probos/api.py` | Progress step labels (Unicode geometric symbols), deployed indicator |

## Constraints

- All SVGs are inline JSX — no external SVG files or icon libraries
- Every SVG uses stroke-based rendering (no fills except small accent dots)
- Colors come from the existing palette variables or hardcoded hex values matching scene.ts
- Active state: amber (`#f0b060`), inactive: dim (`#666680`)
- Do NOT change any functionality — only replace visual representations
- Do NOT modify canvas code, animations, or store logic
- Rebuild UI after: `cd ui && npm run build`
- Run Python tests after api.py changes: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
