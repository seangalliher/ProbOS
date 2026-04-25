# AD-407c: Ward Room HXI Surface

## Context

The Ward Room backend (AD-407a) is complete — WardRoomService with SQLite, 11 API endpoints, 5 WebSocket event types, credibility system. But there's no way to see or interact with it from the HXI. This AD builds the Ward Room panel.

**Design document:** `docs/development/ward-room-design.md` — read this for full context.

**Backend API reference (already built):**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/wardroom/channels` | List all channels |
| POST | `/api/wardroom/channels` | Create custom channel |
| GET | `/api/wardroom/channels/{id}/threads` | List threads (query: limit, offset, sort) |
| POST | `/api/wardroom/channels/{id}/threads` | Create thread |
| GET | `/api/wardroom/threads/{id}` | Thread detail + nested post tree |
| POST | `/api/wardroom/threads/{id}/posts` | Reply to thread |
| POST | `/api/wardroom/posts/{id}/endorse` | Endorse a post (up/down/unvote) |
| POST | `/api/wardroom/threads/{id}/endorse` | Endorse a thread |
| POST | `/api/wardroom/channels/{id}/subscribe` | Subscribe/unsubscribe |
| GET | `/api/wardroom/agent/{id}/credibility` | Get agent credibility |
| GET | `/api/wardroom/notifications` | Get unread counts (query: agent_id) |

**TypeScript types already defined** in `ui/src/store/types.ts`: `WardRoomChannel`, `WardRoomThread`, `WardRoomPost`, `WardRoomCredibility`.

**Key design principle:** The Ward Room panel is a **left-side sliding drawer** — the mirror of the BridgePanel (right-side drawer, `ui/src/components/BridgePanel.tsx`). Same glass morphism pattern, same slide animation, same z-index layer. Use BridgePanel as your structural template.

## Part 1: Store State & Actions (`ui/src/store/useStore.ts`)

### State additions to `HXIState`:

```typescript
// Ward Room HXI (AD-407c)
wardRoomOpen: boolean;
wardRoomActiveChannel: string | null;  // channel ID
wardRoomThreads: WardRoomThread[];
wardRoomActiveThread: string | null;   // thread ID
wardRoomThreadDetail: { thread: WardRoomThread; posts: WardRoomPost[] } | null;
wardRoomUnread: Record<string, number>;  // channel_id → unread count
```

### Initial state values:

```typescript
wardRoomOpen: false,
wardRoomActiveChannel: null,
wardRoomThreads: [],
wardRoomActiveThread: null,
wardRoomThreadDetail: null,
wardRoomUnread: {},
```

### Actions to add:

```typescript
// Ward Room HXI actions (AD-407c)
openWardRoom: (channelId?: string) => void;
closeWardRoom: () => void;
selectWardRoomChannel: (channelId: string) => void;
selectWardRoomThread: (threadId: string) => void;
closeWardRoomThread: () => void;
refreshWardRoomThreads: () => void;
refreshWardRoomUnread: () => void;
```

### Action implementations:

```typescript
openWardRoom: (channelId?: string) => {
  set({ wardRoomOpen: true });
  if (channelId) {
    get().selectWardRoomChannel(channelId);
  } else {
    // Auto-select first channel if none specified
    const channels = get().wardRoomChannels;
    if (channels.length > 0 && !get().wardRoomActiveChannel) {
      get().selectWardRoomChannel(channels[0].id);
    }
  }
  get().refreshWardRoomUnread();
},

closeWardRoom: () => {
  set({ wardRoomOpen: false });
},

selectWardRoomChannel: async (channelId: string) => {
  set({ wardRoomActiveChannel: channelId, wardRoomActiveThread: null, wardRoomThreadDetail: null });
  try {
    const resp = await fetch(`/api/wardroom/channels/${channelId}/threads?limit=50&sort=recent`);
    if (resp.ok) {
      const data = await resp.json();
      set({ wardRoomThreads: data.threads || [] });
    }
  } catch { /* swallow */ }
},

selectWardRoomThread: async (threadId: string) => {
  set({ wardRoomActiveThread: threadId });
  try {
    const resp = await fetch(`/api/wardroom/threads/${threadId}`);
    if (resp.ok) {
      const data = await resp.json();
      set({ wardRoomThreadDetail: { thread: data.thread, posts: data.posts || [] } });
    }
  } catch { /* swallow */ }
},

closeWardRoomThread: () => {
  set({ wardRoomActiveThread: null, wardRoomThreadDetail: null });
},

refreshWardRoomThreads: async () => {
  const channelId = get().wardRoomActiveChannel;
  if (!channelId) return;
  try {
    const resp = await fetch(`/api/wardroom/channels/${channelId}/threads?limit=50&sort=recent`);
    if (resp.ok) {
      const data = await resp.json();
      set({ wardRoomThreads: data.threads || [] });
    }
  } catch { /* swallow */ }
},

refreshWardRoomUnread: async () => {
  try {
    // Use "captain" as the agent_id for the human user
    const resp = await fetch('/api/wardroom/notifications?agent_id=captain');
    if (resp.ok) {
      const data = await resp.json();
      set({ wardRoomUnread: data.unread || {} });
    }
  } catch { /* swallow */ }
},
```

### Import additions:

Add `WardRoomThread`, `WardRoomPost` to the existing imports from `./types`.

### WebSocket event handler updates:

Replace the existing no-op Ward Room case block with:

```typescript
// Ward Room events (AD-407c)
case 'ward_room_thread_created': {
  // Refresh threads if we're viewing the affected channel
  const channelId = (data as any).channel_id;
  if (get().wardRoomActiveChannel === channelId) {
    get().refreshWardRoomThreads();
  }
  // Update unread counts
  get().refreshWardRoomUnread();
  break;
}
case 'ward_room_post_created': {
  // Refresh thread detail if we're viewing the affected thread
  const threadId = (data as any).thread_id;
  if (get().wardRoomActiveThread === threadId) {
    get().selectWardRoomThread(threadId);
  }
  get().refreshWardRoomUnread();
  break;
}
case 'ward_room_endorsement':
case 'ward_room_mod_action':
case 'ward_room_mention': {
  get().refreshWardRoomUnread();
  break;
}
```

### State snapshot hydration:

In the `state_snapshot` handler, the existing `wardRoomChannels` hydration should already be there. If not, ensure:

```typescript
if ((data as any).ward_room_channels) {
  set({ wardRoomChannels: (data as any).ward_room_channels as WardRoomChannel[] });
}
```

When channels load, also refresh unread counts:

```typescript
if ((data as any).ward_room_channels) {
  set({ wardRoomChannels: (data as any).ward_room_channels as WardRoomChannel[] });
  // Refresh unread counts after channels load
  get().refreshWardRoomUnread();
}
```

## Part 2: Ward Room Panel Component (`ui/src/components/wardroom/WardRoomPanel.tsx`)

Create a new directory `ui/src/components/wardroom/` with an `index.ts` barrel export.

### Panel Structure

This is a **left-side sliding drawer** — the mirror image of BridgePanel. Use BridgePanel (`ui/src/components/BridgePanel.tsx`) as your structural reference.

```typescript
export function WardRoomPanel() {
  const open = useStore(s => s.wardRoomOpen);
  const onClose = useStore(s => s.closeWardRoom);
  // ... rest of state

  return (
    <div style={{
      position: 'fixed',
      top: 0, left: 0, bottom: 0,   // LEFT side (BridgePanel uses right: 0)
      width: 420,
      background: 'rgba(10, 10, 18, 0.92)',
      backdropFilter: 'blur(16px)',
      WebkitBackdropFilter: 'blur(16px)',
      borderRight: '1px solid rgba(240, 176, 96, 0.15)',  // borderRight (not borderLeft)
      zIndex: 20,
      transform: open ? 'translateX(0)' : 'translateX(-100%)',  // Slide from LEFT
      transition: 'transform 0.25s ease-out',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: "'JetBrains Mono', monospace",
      pointerEvents: open ? 'auto' : 'none',
      color: '#e0dcd4',
    }}>
      <WardRoomHeader onClose={onClose} />
      <WardRoomBody />
    </div>
  );
}
```

### Panel Width: 420px

Wider than BridgePanel (380px) because thread content needs more reading room.

### Layout inside the panel:

The panel has two modes based on whether a thread is selected:

**Channel View (no thread selected):**
```
┌──────────────────────────┐
│ WARD ROOM           [✕]  │  ← Header (fixed)
├──────────────────────────┤
│ ▼ Channels               │  ← Channel list (scrollable sidebar)
│   ● All Hands        (2) │     Unread count badges
│   ● Engineering          │
│   ● Science              │
│   ● Medical              │
│   ● Security             │
│   ● Bridge               │
├──────────────────────────┤
│ # All Hands              │  ← Active channel name
│                          │
│ ┌────────────────────┐   │  ← Thread cards (scrollable)
│ │ Title of thread    │   │
│ │ by Wesley · 3 min  │   │
│ │ ▲ 5  💬 3          │   │
│ └────────────────────┘   │
│ ┌────────────────────┐   │
│ │ Another thread     │   │
│ │ by Worf · 1 hr     │   │
│ │ ▲ 2  💬 1          │   │
│ └────────────────────┘   │
│                          │
├──────────────────────────┤
│ [New Thread...]          │  ← New thread input area
└──────────────────────────┘
```

**Thread Detail View (thread selected):**
```
┌──────────────────────────┐
│ ← Back  # All Hands [✕]  │  ← Header with back button
├──────────────────────────┤
│ Title of thread          │  ← Thread title + body
│ by Wesley · 3 min ago   │
│ Thread body text here... │
│ ▲ 5  ▼                   │  ← Endorsement buttons
├──────────────────────────┤
│ ┌────────────────────┐   │  ← Posts (scrollable, nested)
│ │ Worf:              │   │
│ │ "I concur."        │   │
│ │ ▲ 2  ▼  · 2 min    │   │
│ │  ┌─────────────┐   │   │
│ │  │ Wesley:      │   │   │  ← Nested reply
│ │  │ "Thank you!" │   │   │
│ │  │ ▲ 1  ▼       │   │   │
│ │  └─────────────┘   │   │
│ └────────────────────┘   │
│                          │
├──────────────────────────┤
│ [Reply...]               │  ← Reply input
└──────────────────────────┘
```

## Part 3: Sub-Components

### `WardRoomHeader.tsx` (~40 lines)

Fixed header bar at the top of the panel.

**Channel view mode:**
- "WARD ROOM" title in uppercase, `fontSize: 11`, `letterSpacing: 1.5`, `color: '#f0b060'`
- Close button (✕) at right
- Same style as BridgePanel header

**Thread detail mode:**
- Back button (← arrow) at left — calls `closeWardRoomThread()`
- Channel name `# {channelName}` in center
- Close button (✕) at right

### `WardRoomChannelList.tsx` (~80 lines)

Scrollable channel list. Renders each channel as a clickable row.

```typescript
// For each channel:
<div onClick={() => selectWardRoomChannel(channel.id)} style={{
  padding: '6px 12px',
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  background: isActive ? 'rgba(240, 176, 96, 0.08)' : 'transparent',
  borderLeft: isActive ? '2px solid #f0b060' : '2px solid transparent',
}}>
  <span style={{ color: channelTypeColor(channel), fontSize: 12 }}>#</span>
  <span style={{ flex: 1, fontSize: 13, color: isActive ? '#f0b060' : '#e0dcd4' }}>
    {channel.name}
  </span>
  {unreadCount > 0 && (
    <span style={{
      background: '#f0b060',
      color: '#0a0a12',
      borderRadius: 8,
      padding: '1px 6px',
      fontSize: 10,
      fontWeight: 700,
    }}>{unreadCount}</span>
  )}
</div>
```

**Channel type colors (for the `#` icon):**
- `ship`: `#f0b060` (amber — all hands)
- `department`: use department color from the map (`engineering: '#b0a050'`, `science: '#50b0a0'`, `medical: '#5090d0'`, `security: '#d05050'`, `bridge: '#d0a030'`)
- `custom`: `#8888a0` (neutral)
- `dm`: `#8888a0`

**Channel ordering:**
1. Ship channel first (always)
2. Department channels alphabetically
3. Custom channels alphabetically
4. Don't show archived channels
5. Don't show DM channels (those use the Agent Profile Panel)

### `WardRoomThreadList.tsx` (~120 lines)

Scrollable list of thread cards for the active channel.

**Thread card:**
```typescript
<div onClick={() => selectWardRoomThread(thread.id)} style={{
  padding: '10px 12px',
  borderBottom: '1px solid rgba(255,255,255,0.06)',
  cursor: 'pointer',
  // Hover: background rgba(255,255,255,0.03)
}}>
  {thread.pinned && <span style={{ color: '#f0b060', fontSize: 10 }}>PINNED</span>}
  <div style={{ fontSize: 14, color: '#e0dcd4', fontWeight: 500 }}>
    {thread.title}
  </div>
  <div style={{ fontSize: 11, color: '#8888a0', marginTop: 4 }}>
    by {thread.author_callsign || 'unknown'} · {timeAgo(thread.last_activity)}
  </div>
  <div style={{ fontSize: 11, color: '#666680', marginTop: 4, display: 'flex', gap: 12 }}>
    <span>▲ {thread.net_score}</span>
    <span>💬 {thread.reply_count}</span>
  </div>
</div>
```

**"New Thread" button** at the bottom of the thread list:

Clicking opens a small inline form with:
- Title input (single line)
- Body textarea (3-4 rows)
- Post button

On submit: `POST /api/wardroom/channels/{channelId}/threads` with `author_id: "captain"`, `author_callsign: "Captain"`. Then refresh the thread list.

### `WardRoomThreadDetail.tsx` (~150 lines)

The thread detail view when a thread is selected.

**Thread header section:**
- Title in `fontSize: 16`, `fontWeight: 600`
- Author callsign + time ago in `fontSize: 12, color: '#8888a0'`
- Body text in `fontSize: 13`, rendered with ReactMarkdown (import from `react-markdown`)
- Endorsement buttons: ▲ and ▼ arrows + net score

**Posts section:**
- Scrollable list of posts
- Render recursively using `WardRoomPostItem` for nested children

**Reply input at bottom:**
- Single textarea + Send button
- On submit: `POST /api/wardroom/threads/{threadId}/posts` with `author_id: "captain"`, `author_callsign: "Captain"`. Then refresh thread detail.

### `WardRoomPostItem.tsx` (~80 lines)

Recursive post component for rendering nested replies.

```typescript
function WardRoomPostItem({ post, threadId, depth = 0 }: {
  post: WardRoomPost;
  threadId: string;
  depth?: number;
}) {
  const [replying, setReplying] = useState(false);
  const [replyText, setReplyText] = useState('');

  return (
    <div style={{
      marginLeft: depth * 16,  // Indent for nesting (max 4 levels visually)
      borderLeft: depth > 0 ? '1px solid rgba(255,255,255,0.08)' : 'none',
      paddingLeft: depth > 0 ? 12 : 0,
      paddingTop: 8,
      paddingBottom: 4,
    }}>
      <div style={{ fontSize: 12, color: '#f0b060' }}>
        {post.author_callsign || 'unknown'}
        <span style={{ color: '#666680', marginLeft: 8 }}>{timeAgo(post.created_at)}</span>
      </div>
      <div style={{ fontSize: 13, color: '#e0dcd4', marginTop: 2 }}>
        {post.body}
      </div>
      <div style={{ fontSize: 11, color: '#666680', marginTop: 4, display: 'flex', gap: 12 }}>
        <EndorsementButtons targetId={post.id} targetType="post" netScore={post.net_score} />
        <span onClick={() => setReplying(!replying)} style={{ cursor: 'pointer' }}>Reply</span>
      </div>
      {replying && (
        <ReplyInput threadId={threadId} parentId={post.id} onDone={() => setReplying(false)} />
      )}
      {post.children?.map(child => (
        <WardRoomPostItem key={child.id} post={child} threadId={threadId} depth={Math.min(depth + 1, 4)} />
      ))}
    </div>
  );
}
```

### `WardRoomEndorsement.tsx` (~50 lines)

Endorsement buttons (▲ score ▼) used on both threads and posts.

```typescript
function EndorsementButtons({ targetId, targetType, netScore }: {
  targetId: string;
  targetType: 'thread' | 'post';
  netScore: number;
}) {
  const [score, setScore] = useState(netScore);

  const endorse = async (direction: 'up' | 'down') => {
    const endpoint = targetType === 'thread'
      ? `/api/wardroom/threads/${targetId}/endorse`
      : `/api/wardroom/posts/${targetId}/endorse`;
    try {
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ voter_id: 'captain', direction }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setScore(data.net_score);
      }
    } catch { /* swallow */ }
  };

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <span onClick={() => endorse('up')} style={{ cursor: 'pointer', color: '#50c878' }}>▲</span>
      <span style={{ fontSize: 12, minWidth: 16, textAlign: 'center' as const }}>{score}</span>
      <span onClick={() => endorse('down')} style={{ cursor: 'pointer', color: '#c84858' }}>▼</span>
    </span>
  );
}
```

### `index.ts` — Barrel export

```typescript
export { WardRoomPanel } from './WardRoomPanel';
```

## Part 4: Ward Room Toggle Button

Add a toggle button to open/close the Ward Room, mirroring the Bridge toggle at the top-right.

### In `IntentSurface.tsx` or as a standalone component:

Add a "WARD ROOM" button at the top-left of the screen:

```typescript
// Position: fixed, top: 12, left: 12, zIndex: 25
// Mirror of the Bridge toggle button (top: 12, right: 12)
```

**Implementation:** Add this to `App.tsx` as a simple inline element, similar to how the BridgePanel toggle works. Read `wardRoomOpen` from store. Show unread total badge.

```typescript
function WardRoomToggle() {
  const open = useStore(s => s.wardRoomOpen);
  const openWardRoom = useStore(s => s.openWardRoom);
  const closeWardRoom = useStore(s => s.closeWardRoom);
  const unread = useStore(s => s.wardRoomUnread);
  const totalUnread = Object.values(unread).reduce((sum, n) => sum + n, 0);

  return (
    <div
      onClick={() => open ? closeWardRoom() : openWardRoom()}
      style={{
        position: 'fixed',
        top: 12, left: 12,
        zIndex: 25,
        padding: '6px 12px',
        background: 'rgba(10, 10, 18, 0.75)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        border: `1px solid rgba(240, 176, 96, ${open ? 0.35 : 0.15})`,
        borderRadius: 6,
        cursor: 'pointer',
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: 1.5,
        fontFamily: "'JetBrains Mono', monospace",
        color: open ? '#f0b060' : '#8888a0',
        userSelect: 'none' as const,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
      }}
    >
      WARD ROOM
      {totalUnread > 0 && (
        <span style={{
          background: '#f0b060',
          color: '#0a0a12',
          borderRadius: 8,
          padding: '1px 6px',
          fontSize: 9,
          fontWeight: 700,
        }}>{totalUnread}</span>
      )}
    </div>
  );
}
```

**Important:** Hide this toggle when the Ward Room panel is already open (or keep it visible but highlighted — your choice; the BridgePanel pattern hides its toggle when the panel is open).

## Part 5: App.tsx Integration

Add the WardRoomPanel and WardRoomToggle to App.tsx:

```typescript
import { WardRoomPanel } from './components/wardroom';
```

Add inside the root div, alongside existing components:

```typescript
<WardRoomPanel />
```

Also add the WardRoomToggle component (either inline in App.tsx or as a separate import).

## Part 6: Sphere Click → Channel Integration

This connects clicking a group sphere on the canvas to opening the Ward Room channel.

### In `CognitiveCanvas.tsx` or the relevant click handler:

When a **group sphere** (team cluster label/sphere) is clicked, find the matching Ward Room channel and open it:

```typescript
// When group sphere is clicked:
const handleGroupClick = (groupName: string) => {
  const channels = useStore.getState().wardRoomChannels;
  const channel = channels.find(c =>
    c.name.toLowerCase() === groupName.toLowerCase() ||
    c.department.toLowerCase() === groupName.toLowerCase()
  );
  if (channel) {
    useStore.getState().openWardRoom(channel.id);
  }
};
```

**Implementation note:** Check how group/cluster labels are currently rendered in the canvas. If clicking group spheres isn't wired up yet, skip this part — it can be added in AD-408b when the canvas layout gets assignment clusters. Just add the `openWardRoom` action call point comment: `// TODO: AD-408b — wire group sphere click → openWardRoom(channelId)`.

## Part 7: Utility Functions

### `timeAgo` helper

Create a small `timeAgo` function (either in the wardroom directory or a shared utils file):

```typescript
function timeAgo(timestamp: number): string {
  const seconds = Math.floor(Date.now() / 1000 - timestamp);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}
```

This can be defined locally in the wardroom components or extracted to a shared utility.

## Part 8: Tests

### Vitest Tests (`ui/src/__tests__/WardRoomPanel.test.tsx`)

Use the same pattern as `ui/src/__tests__/AgentProfilePanel.test.tsx` — test store actions, not DOM rendering (since we don't have full React rendering infrastructure in tests).

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store/useStore';

beforeEach(() => {
  useStore.setState({
    wardRoomOpen: false,
    wardRoomActiveChannel: null,
    wardRoomThreads: [],
    wardRoomActiveThread: null,
    wardRoomThreadDetail: null,
    wardRoomUnread: {},
    wardRoomChannels: [
      {
        id: 'ch1', name: 'All Hands', channel_type: 'ship' as const,
        department: '', created_by: 'system', created_at: 1000,
        archived: false, description: 'Ship-wide channel',
      },
      {
        id: 'ch2', name: 'Engineering', channel_type: 'department' as const,
        department: 'engineering', created_by: 'system', created_at: 1000,
        archived: false, description: '',
      },
    ],
  });
});
```

**Required test cases:**

1. `test_openWardRoom_sets_open` — `openWardRoom()` sets `wardRoomOpen: true`
2. `test_openWardRoom_with_channelId` — `openWardRoom('ch2')` sets active channel to ch2
3. `test_openWardRoom_auto_selects_first` — `openWardRoom()` without channelId selects first channel if none active
4. `test_closeWardRoom` — `closeWardRoom()` sets `wardRoomOpen: false`
5. `test_selectWardRoomChannel_clears_thread` — selecting a channel clears `wardRoomActiveThread` and `wardRoomThreadDetail`
6. `test_closeWardRoomThread` — `closeWardRoomThread()` clears active thread and detail
7. `test_wardRoomUnread_badge` — setting `wardRoomUnread` with counts updates state
8. `test_wardRoom_hidden_when_closed` — `wardRoomOpen` defaults to false
9. `test_wardRoom_websocket_event_updates_unread` — handleEvent with `ward_room_thread_created` triggers state change (test the event type is recognized)

**Note:** Tests 2 and 4-6 are synchronous store tests. Tests that call `selectWardRoomChannel` or `selectWardRoomThread` involve fetch calls — for these, either mock fetch or test only the synchronous state changes (the immediate `set()` calls before the async fetch).

### Backend test: API endpoint for channels in snapshot

Check that `tests/test_api_wardroom.py` already covers channel listing. No new backend tests needed — this AD is frontend-only.

## Verification

```bash
# Frontend tests
cd ui && npx vitest run --reporter=verbose

# TypeScript build
cd ui && npm run build

# Backend tests still pass (no backend changes)
uv run pytest tests/ --tb=short -q
```

All tests must pass. Zero TypeScript build errors.

## Styling Reference (Glass Morphism Cheat Sheet)

Use these consistently:

| Element | Style |
|---------|-------|
| Panel background | `rgba(10, 10, 18, 0.92)`, `blur(16px)` |
| Panel border | `1px solid rgba(240, 176, 96, 0.15)` |
| Active item highlight | `rgba(240, 176, 96, 0.08)` bg, `2px solid #f0b060` left border |
| Section dividers | `1px solid rgba(255,255,255,0.06)` |
| Primary text | `#e0dcd4` |
| Secondary text | `#8888a0` |
| Dim text | `#666680` |
| Accent color | `#f0b060` (amber) |
| Upvote color | `#50c878` (green) |
| Downvote color | `#c84858` (red) |
| Badge background | `#f0b060`, text `#0a0a12` |
| Section headers | `fontSize: 10, textTransform: 'uppercase', letterSpacing: 1.5, fontWeight: 700` |
| Body font | `'Inter', sans-serif` for content text |
| UI font | `'JetBrains Mono', monospace` for labels, headers |
| Border radius | 6px for buttons/badges, 8px for cards, 12px for panels |

## Commit Message

```
Add Ward Room HXI panel with channels, threads, and endorsements (AD-407c)

Left-side sliding drawer with channel list, thread browsing, nested
replies, and endorsement buttons. Ward Room toggle button with unread
badges. WebSocket events now refresh active views. Glass morphism
styling matching existing HXI components.
```

## What NOT to Build

- Agent posting/perception (AD-407b — agents don't post autonomously yet)
- Channel creation UI (Captain can create channels but the UI for this is Phase 2)
- Moderation UI (mod actions, pin/lock — Phase 4)
- Thread sorting controls (hardcoded to "recent" for now)
- Subscription management UI
- Credibility display (Phase 4)
- Edit post UI
- Search/filter
- Markdown rendering in thread bodies if `react-markdown` is not already a dependency — use plain text instead. Check `package.json` first. If `react-markdown` is present, use it.
