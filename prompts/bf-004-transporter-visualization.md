# Build Prompt: Transporter HXI Visualization (BF-004)

## Parallel Build Info
- **Builder:** Builder 1 (main worktree `d:\ProbOS`)
- **File footprint:** `ui/src/components/IntentSurface.tsx` ONLY
- **No overlap with:** Builder 2 (Python-only: `src/probos/sif.py`, `src/probos/runtime.py`, `tests/test_sif.py`)

## Context

The Transporter Pattern (AD-330–336) emits 6 event types during parallel chunk
builds. The Zustand store already processes all 6 events and correctly updates
`transporterProgress` state (see `useStore.ts` lines 690–783). The types are
fully defined in `store/types.ts` (lines 97–111). Chat messages are pushed for
each event.

**The bug:** No component reads `transporterProgress` from the store to render
a visual progress card. The data flows from server → WebSocket → store → nowhere.

## Data Shape (already defined — do NOT modify types.ts)

```typescript
interface TransporterChunkStatus {
  chunk_id: string;
  description: string;
  target_file: string;
  status: 'pending' | 'executing' | 'done' | 'failed';
}

interface TransporterProgress {
  phase: 'decomposed' | 'executing' | 'executed' | 'assembled' | 'valid' | 'invalid';
  chunks: TransporterChunkStatus[];
  waves_completed: number;
  total_chunks: number;
  successful: number;
  failed: number;
}
```

## Changes

### File: `ui/src/components/IntentSurface.tsx`

**1. Add store selector** (near the other `useStore` selectors around lines 40–49):

```typescript
const transporterProgress = useStore((s) => s.transporterProgress);
```

**2. Add a floating Transporter Progress Card** — render it between the chat
messages area and the neural pulse indicator (around line 1052, after the chat
`</div>` but before the neural pulse).

**Design requirements:**

- **Only render** when `transporterProgress !== null`
- **Auto-clears** — the store sets `transporterProgress = null` after
  `transporter_validated`, so the card disappears automatically
- **Color palette:** Teal/cyan theme to match science/transporter:
  - Primary: `#50c8e0`
  - Background: `rgba(80, 200, 224, 0.08)`
  - Border: `rgba(80, 200, 224, 0.2)`
- **Follow the BuildFailureReport card styling** (lines 691–846) for layout:
  - Container: `marginTop: 8, maxWidth: '80%'`
  - Header card: `padding: '8px 12px'`, `borderRadius: 8`
  - Font sizes: 12–13 main, 10–11 secondary
  - Monospace for technical details

**Card content:**

1. **Header row:** Teal badge with phase name (e.g., "EXECUTING") + progress
   fraction (e.g., "3 / 8 chunks")
2. **Progress bar:** Visual bar showing `successful / total_chunks` ratio.
   Background: `rgba(80, 200, 224, 0.15)`, fill: `#50c8e0`. Red fill for
   failed chunks if any.
3. **Chunk list:** Each chunk as a compact row:
   - Status dot: gray (pending), pulsing amber (executing), green (done),
     red (failed)
   - `description` text (fontSize 11)
   - `target_file` in monospace (fontSize 10, color `#8888a0`)
4. **Footer stats** (only if visible): waves completed, failed count (red if > 0)

**Rendering pattern** — use inline styles following the existing component
conventions. Do NOT create a separate component file — keep it in
IntentSurface.tsx like the BuildFailureReport card.

## Constraints

- Modify ONLY `ui/src/components/IntentSurface.tsx`
- Do NOT modify `useStore.ts`, `types.ts`, `useWebSocket.ts`, or any Python files
- Do NOT create new component files
- Follow existing inline style patterns (no CSS modules, no Tailwind)
- The card must render correctly with 1–20+ chunks
- Use `key={chunk.chunk_id}` for the chunk list
