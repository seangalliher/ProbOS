# Build Prompt: HXI Build Dashboard (AD-373)

## File Footprint
- `ui/src/types.ts` (MODIFIED) — add `BuildQueueItem` interface + `buildQueue` field on `ChatMessage`
- `ui/src/store/useStore.ts` (MODIFIED) — add `buildQueue` state + event handlers
- `ui/src/components/IntentSurface.tsx` (MODIFIED) — render Build Dashboard card
- **All UI files, no Python changes**

## Context

AD-373 adds real-time build queue visibility to the HXI. The backend
(AD-371/372) manages a `BuildQueue` with items progressing through:
`queued → dispatched → building → reviewing → merged/failed`.

The dashboard shows active builds, builds awaiting Captain review, and
provides approve/reject buttons. It follows the same patterns as the
existing transporter progress card (BF-004) and build failure card.

**Color theme:** Engineering amber — `rgba(176, 160, 80, ...)` / `#b0a050`
to match the Engineering department color on the Cognitive Canvas.

---

## Changes

### File: `ui/src/types.ts`

**Add `BuildQueueItem` interface** (after the `TransporterProgress` interface):

```typescript
export interface BuildQueueItem {
  id: string;
  title: string;
  ad_number: number;
  status: 'queued' | 'dispatched' | 'building' | 'reviewing' | 'merged' | 'failed';
  priority: number;
  worktree_path: string;
  builder_id: string;
  error: string;
  file_footprint: string[];
  commit_hash: string;
}
```

### File: `ui/src/store/useStore.ts`

**1. Import `BuildQueueItem`** from `types.ts`.

**2. Add state field** to the `HXIState` interface (in the "Animation events"
section, near `transporterProgress`):

```typescript
buildQueue: BuildQueueItem[] | null;
```

**3. Initialize** in the `create<HXIState>()` call:

```typescript
buildQueue: null,
```

**4. Add event handlers** in the `handleEvent` switch block. Add these cases
after the existing `build_*` cases:

```typescript
case 'build_queue_update': {
  // Full queue snapshot
  const items = (data.items || []) as BuildQueueItem[];
  set({ buildQueue: items.length > 0 ? items : null });
  break;
}

case 'build_queue_item': {
  // Single item update — upsert into existing queue
  const item = data.item as BuildQueueItem;
  if (!item) break;
  const current = get().buildQueue || [];
  const idx = current.findIndex(b => b.id === item.id);
  const updated = [...current];
  if (idx >= 0) {
    updated[idx] = item;
  } else {
    updated.push(item);
  }
  // Remove merged/failed items older than 30s (auto-clear)
  const active = updated.filter(
    b => !['merged', 'failed'].includes(b.status)
  );
  const terminal = updated.filter(
    b => ['merged', 'failed'].includes(b.status)
  );
  set({ buildQueue: [...active, ...terminal].length > 0
    ? [...active, ...terminal] : null });

  // Log status transitions to chat
  if (item.status === 'building') {
    get().addChatMessage('system',
      `Builder started: ${item.title}${item.ad_number ? ` (AD-${item.ad_number})` : ''}`);
  } else if (item.status === 'reviewing') {
    get().addChatMessage('system',
      `Build ready for review: ${item.title}${item.ad_number ? ` (AD-${item.ad_number})` : ''}`);
  } else if (item.status === 'merged') {
    get().addChatMessage('system',
      `Build merged: ${item.title}${item.ad_number ? ` (AD-${item.ad_number})` : ''} → ${item.commit_hash.slice(0, 7)}`);
  } else if (item.status === 'failed') {
    get().addChatMessage('system',
      `Build failed: ${item.title}${item.ad_number ? ` (AD-${item.ad_number})` : ''} — ${item.error}`);
  }
  break;
}
```

### File: `ui/src/components/IntentSurface.tsx`

**1. Add store selector** near the other selectors (around line 50):

```typescript
const buildQueue = useStore((s) => s.buildQueue);
```

**2. Add the Build Dashboard card** immediately after the transporter progress
card (after the closing `)}` of the `{transporterProgress && (...)}` block).

The card should render when `buildQueue` is non-null and has items:

```tsx
{buildQueue && buildQueue.length > 0 && (
  <div style={{ marginTop: 8, maxWidth: '80%', padding: '0 20px' }}>
    <div style={{
      padding: '8px 12px',
      borderRadius: 8,
      background: 'rgba(176, 160, 80, 0.08)',
      border: '1px solid rgba(176, 160, 80, 0.2)',
      fontSize: 12,
      color: '#c8d0e0',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{
          padding: '1px 6px',
          borderRadius: 4,
          background: 'rgba(176, 160, 80, 0.15)',
          border: '1px solid rgba(176, 160, 80, 0.3)',
          color: '#b0a050',
          fontSize: 10,
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '0.5px',
        }}>
          Build Queue
        </span>
        <span style={{ color: '#8888a0', fontSize: 11 }}>
          {buildQueue.filter(b => !['merged', 'failed'].includes(b.status)).length} active
        </span>
      </div>

      {/* Build items list */}
      {buildQueue.map((item) => (
        <div key={item.id} style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 6,
          padding: '4px 0',
          borderBottom: '1px solid rgba(176, 160, 80, 0.1)',
        }}>
          {/* Status dot */}
          <span style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            flexShrink: 0,
            background: item.status === 'merged' ? '#50c878'
              : item.status === 'failed' ? '#ff5555'
              : item.status === 'reviewing' ? '#b0a050'
              : item.status === 'building' ? '#ffaa44'
              : item.status === 'dispatched' ? '#6688cc'
              : '#555566',
            ...(item.status === 'building' ? {
              animation: 'neural-pulse 1.4s ease-in-out infinite',
            } : {}),
          }} />

          {/* Title + AD number */}
          <span style={{ fontSize: 11, color: '#c8d0e0', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {item.title}
            {item.ad_number > 0 && (
              <span style={{ color: '#8888a0', marginLeft: 4 }}>AD-{item.ad_number}</span>
            )}
          </span>

          {/* Status badge */}
          <span style={{
            padding: '1px 5px',
            borderRadius: 3,
            fontSize: 9,
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.3px',
            background: item.status === 'reviewing' ? 'rgba(176, 160, 80, 0.2)' : 'rgba(128, 128, 160, 0.15)',
            color: item.status === 'reviewing' ? '#b0a050'
              : item.status === 'merged' ? '#50c878'
              : item.status === 'failed' ? '#ff5555'
              : '#8888a0',
            border: item.status === 'reviewing' ? '1px solid rgba(176, 160, 80, 0.3)' : '1px solid rgba(128, 128, 160, 0.2)',
          }}>
            {item.status}
          </span>

          {/* Approve / Reject buttons for reviewing items */}
          {item.status === 'reviewing' && (
            <div style={{ display: 'flex', gap: 4 }}>
              <button
                style={{
                  padding: '2px 8px',
                  borderRadius: 4,
                  border: '1px solid rgba(80, 200, 120, 0.3)',
                  background: 'rgba(80, 200, 120, 0.15)',
                  color: '#50c878',
                  fontSize: 10,
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
                onClick={async () => {
                  try {
                    await fetch('/api/build/approve', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ build_id: item.id }),
                    });
                  } catch { /* ignore */ }
                }}
              >
                Approve
              </button>
              <button
                style={{
                  padding: '2px 8px',
                  borderRadius: 4,
                  border: '1px solid rgba(255, 85, 85, 0.3)',
                  background: 'rgba(255, 85, 85, 0.15)',
                  color: '#ff5555',
                  fontSize: 10,
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
                onClick={async () => {
                  try {
                    await fetch('/api/build/reject', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ build_id: item.id }),
                    });
                  } catch { /* ignore */ }
                }}
              >
                Reject
              </button>
            </div>
          )}
        </div>
      ))}

      {/* File footprint for reviewing items */}
      {buildQueue.filter(b => b.status === 'reviewing').map((item) => (
        item.file_footprint.length > 0 && (
          <div key={`fp-${item.id}`} style={{
            marginTop: 4,
            padding: '4px 8px',
            background: 'rgba(176, 160, 80, 0.05)',
            borderRadius: 4,
            fontSize: 10,
            color: '#8888a0',
            fontFamily: 'monospace',
          }}>
            {item.file_footprint.map((f, i) => (
              <div key={i}>{f}</div>
            ))}
          </div>
        )
      ))}
    </div>
  </div>
)}
```

---

## Constraints

- Do NOT modify any Python files
- Do NOT modify `useWebSocket.ts` (all event routing is in the store)
- Follow existing patterns: glass-morph styling, rgba backgrounds, consistent badge/pill formatting
- Use Engineering amber theme (`#b0a050`, `rgba(176, 160, 80, ...)`)
- Status dot colors: queued=gray, dispatched=blue, building=amber-pulsing, reviewing=amber, merged=green, failed=red
- Approve button: green theme. Reject button: red theme
- API endpoints (`/api/build/approve`, `/api/build/reject`) don't exist yet — the UI is ready for when they're wired in
- The `buildQueue` state auto-clears when set to null or empty array
