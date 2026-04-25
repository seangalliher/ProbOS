# Wave 2: Communications UI Polish (BF-053/054/055)

## Context

Sea trial on 2026-03-27 after AD-485 (Communications Command Center) revealed three UI bugs in the Bridge Communications panel and Ward Room DM Activity Log. These are all frontend fixes — the backend APIs already exist and work correctly.

## Prerequisites

- Read `docs/development/roadmap.md` bug tracker entries BF-053 through BF-055
- Read ALL files listed under each fix below before modifying them

---

## Fix 1: Wire Communications section badge count (BF-053)

**Root cause:** `BridgePanel.tsx` line 171 hardcodes `count={0}` on the Communications BridgeSection instead of using actual DM channel data.

**File to modify:**
- `ui/src/components/BridgePanel.tsx`

**Implementation:**

1. The store already has `wardRoomDmChannels` and `refreshWardRoomDmChannels`. Use them to wire the count.

2. At the top of the `BridgePanel` component (after existing store selectors around line 63), add:
```tsx
const dmChannels = useStore(s => s.wardRoomDmChannels);
const refreshDms = useStore(s => s.refreshWardRoomDmChannels);
```

3. Add a `useEffect` to refresh DM channels on mount (import `useEffect` from React — check if it's already imported):
```tsx
useEffect(() => { refreshDms(); }, [refreshDms]);
```

4. Replace line 171:
```tsx
// BEFORE:
<BridgeSection title="Communications" count={0} defaultOpen={false} accentColor="#b080d0">

// AFTER:
<BridgeSection title="Communications" count={dmChannels.length} defaultOpen={false} accentColor="#b080d0">
```

**Tests (add to existing `ui/src/__tests__/` or create `ui/src/__tests__/BridgePanel.test.tsx`):**
1. `test_communications_badge_reflects_dm_count` — mock store with 3 DM channels, verify the Communications section renders `(3)` in the badge

---

## Fix 2: DM Activity Log — thread toggle + auto-refresh (BF-054)

**Root cause:** In `WardRoomPanel.tsx` `DmActivityLog` component (lines 78-89), the "View full thread →" link is inside the `{isExpanded && (...)}` block. It only appears AFTER clicking to expand, but it should be visible in the COLLAPSED state to invite interaction. When expanded, replace it with the full thread body. Also: `refreshDms()` fires only once on mount (line 14) — no polling, so the panel shows stale data.

**File to modify:**
- `ui/src/components/wardroom/WardRoomPanel.tsx`

**Implementation:**

### 2a. Fix thread toggle visibility

Replace the rendering logic inside the `allEntries.map()` callback (lines 62-91) with this pattern:

```tsx
{/* Header row — always visible */}
<div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
  <span style={{ color: '#6a6a7a', fontSize: 10 }}>{ts}</span>
  <span style={{ color: '#c0bab0', fontWeight: 600, fontSize: 11 }}>
    {ch.description || ch.name}
  </span>
  {captainBadge && (
    <span style={{
      fontSize: 9, padding: '1px 5px', borderRadius: 3,
      background: 'rgba(240,176,96,0.15)', color: '#f0b060',
      fontWeight: 700, letterSpacing: 0.5,
    }}>CPT</span>
  )}
</div>

{/* Body — preview when collapsed, full when expanded */}
<div style={{ color: '#8888a0', fontSize: 11, lineHeight: 1.4 }}>
  {isExpanded ? (t.body || '') : preview}
</div>

{/* Action link — "View full thread" when COLLAPSED, nothing or "Open in Ward Room" when expanded */}
{!isExpanded ? (
  <div style={{ marginTop: 4 }}>
    <span style={{ fontSize: 10, color: '#6a6a7a' }}>
      View full thread →
    </span>
  </div>
) : (
  <div style={{ marginTop: 6 }}>
    <span
      onClick={e => { e.stopPropagation(); selectChannel(ch.id); }}
      style={{
        fontSize: 10, color: '#f0b060', cursor: 'pointer',
        textDecoration: 'underline',
      }}
    >
      Open in Ward Room →
    </span>
  </div>
)}
```

Key changes:
- "View full thread →" visible in **collapsed** state (muted color, acts as invitation)
- Clicking the entry expands it (existing behavior)
- When **expanded**, shows "Open in Ward Room →" (active color, clickable — navigates to the DM channel in Ward Room)

### 2b. Add auto-refresh polling

In the `DmActivityLog` component, add a polling interval to refresh DM data every 15 seconds:

```tsx
useEffect(() => {
  refresh();
  const interval = setInterval(refresh, 15000);
  return () => clearInterval(interval);
}, [refresh]);
```

Replace the existing `useEffect(() => { refresh(); }, [refresh]);` on line 14.

**Tests:**
1. `test_view_thread_visible_when_collapsed` — render DmActivityLog with mock data, verify "View full thread" text is present without clicking/expanding
2. `test_open_in_wardroom_visible_when_expanded` — click an entry, verify "Open in Ward Room" text appears

---

## Fix 3: Captain can reply to DMs (BF-055)

**Root cause:** The DM Activity Log is read-only — no input field or reply mechanism. When agents DM the Captain, the message appears but the Captain can't respond. This violates the HXI Cockpit View Principle: every agent-mediated capability requires direct manual control.

**Files to modify:**
- `ui/src/components/wardroom/WardRoomPanel.tsx` — add reply input to DmActivityLog entries
- No backend changes needed — `POST /api/wardroom/channels/{channel_id}/threads` already exists and accepts `author_id`, `title`, `body`, `author_callsign`

**Implementation:**

### 3a. Add reply state and handler to DmActivityLog

Add state for the reply input:
```tsx
const [replyingTo, setReplyingTo] = useState<string | null>(null);
const [replyText, setReplyText] = useState('');
const [sending, setSending] = useState(false);
```

Add the reply handler:
```tsx
const handleReply = async (channelId: string) => {
  if (!replyText.trim() || sending) return;
  setSending(true);
  try {
    await fetch(`/api/wardroom/channels/${channelId}/threads`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        author_id: 'captain',
        title: `Captain reply`,
        body: replyText.trim(),
        author_callsign: 'Captain',
      }),
    });
    setReplyText('');
    setReplyingTo(null);
    refresh(); // Refresh DM list to show the new message
  } catch { /* swallow */ }
  setSending(false);
};
```

### 3b. Add reply UI to expanded DM entries

Inside the `isExpanded` block (after the "Open in Ward Room →" link from Fix 2), add a reply button and input:

```tsx
{isExpanded && (
  <div style={{ marginTop: 6 }}>
    <span
      onClick={e => { e.stopPropagation(); selectChannel(ch.id); }}
      style={{
        fontSize: 10, color: '#f0b060', cursor: 'pointer',
        textDecoration: 'underline',
      }}
    >
      Open in Ward Room →
    </span>

    {/* Reply controls */}
    {replyingTo === (t.id || `${i}`) ? (
      <div style={{ marginTop: 6 }} onClick={e => e.stopPropagation()}>
        <textarea
          value={replyText}
          onChange={e => setReplyText(e.target.value)}
          placeholder="Reply as Captain..."
          rows={2}
          style={{
            width: '100%', background: 'rgba(255,255,255,0.06)',
            border: '1px solid rgba(240,176,96,0.2)', borderRadius: 4,
            padding: '6px 8px', color: '#e0dcd4', fontSize: 11,
            fontFamily: "'JetBrains Mono', monospace", resize: 'vertical',
          }}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleReply(ch.id);
            }
          }}
          autoFocus
        />
        <div style={{ display: 'flex', gap: 6, marginTop: 4, justifyContent: 'flex-end' }}>
          <button
            onClick={e => { e.stopPropagation(); setReplyingTo(null); setReplyText(''); }}
            style={{
              background: 'none', border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 4, padding: '3px 8px', color: '#6a6a7a',
              fontSize: 10, cursor: 'pointer',
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            Cancel
          </button>
          <button
            onClick={e => { e.stopPropagation(); handleReply(ch.id); }}
            disabled={sending || !replyText.trim()}
            style={{
              background: 'rgba(240,176,96,0.15)',
              border: '1px solid rgba(240,176,96,0.3)',
              borderRadius: 4, padding: '3px 10px', color: '#f0b060',
              fontSize: 10, cursor: sending ? 'wait' : 'pointer',
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            {sending ? '...' : 'Send'}
          </button>
        </div>
      </div>
    ) : (
      <span
        onClick={e => { e.stopPropagation(); setReplyingTo(t.id || `${i}`); }}
        style={{
          display: 'inline-block', marginLeft: 12,
          fontSize: 10, color: '#b080d0', cursor: 'pointer',
        }}
      >
        Reply
      </span>
    )}
  </div>
)}
```

Key behaviors:
- Expanded DM entries show a "Reply" link next to "Open in Ward Room →"
- Clicking "Reply" opens a textarea inline
- Enter sends (Shift+Enter for newline), Cancel closes
- Posts as `author_id: 'captain'`, `author_callsign: 'Captain'` to the DM channel
- After sending, refreshes the DM list and closes the reply input

**Tests:**
1. `test_reply_button_visible_when_expanded` — expand a DM entry, verify "Reply" text is present
2. `test_reply_textarea_opens_on_click` — click Reply, verify textarea appears with "Reply as Captain..." placeholder
3. `test_reply_sends_to_correct_channel` — mock fetch, type text, submit, verify POST to `/api/wardroom/channels/{id}/threads` with correct `author_id: 'captain'`

---

## Verification

After implementing all fixes:

1. **Vitest** — `cd ui && npx vitest run` — all existing + new tests pass
2. **Visual verification** — `uv run probos serve --interactive`:
   - Bridge panel Communications section shows `(N)` where N = actual DM channel count
   - DM Activity Log shows "View full thread →" on collapsed entries
   - Clicking an entry expands it, shows full body + "Open in Ward Room →" + "Reply"
   - Clicking "Reply" opens textarea, sending works, message appears in DM channel
   - DM list auto-refreshes every 15s (new messages appear without manual refresh)

## Files Summary

**Modify:**
- `ui/src/components/BridgePanel.tsx` — wire DM count to Communications badge
- `ui/src/components/wardroom/WardRoomPanel.tsx` — thread toggle fix, auto-refresh, Captain reply input

**No backend changes required.**

## Tracking

Update on completion:
- `PROGRESS.md` — mark BF-053, BF-054, BF-055 closed
- `DECISIONS.md` — add brief wave summary
- `docs/development/roadmap.md` — update bug tracker entries to Closed
