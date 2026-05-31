# AD-792 (Wave 195, v2) — Thread sidebar for Compact Yeo

**Wave:** 195. Single Builder commit at completion.
**Sequence:** AD-792 ([#716](https://github.com/seangalliher/ProbOS/issues/716)).
**Builds on:** AD-791a / AD-827 (Wave 193) substrate + Wave 194 (AD-794 auto-name, AD-809 personality). Backend `/api/threads` CRUD + search + recents endpoints all already exist. Frontend store slices `chatThreads`, `threadIdByAgent`, `activeThreadId` + actions `setChatThread`, `setThreadForAgent`, `setActiveThread`, `hydrateChatThreads` are wired and in production use (verified at `useStore.ts:297-410`, `useStore.ts:603-607`, `useStore.ts:1034-1044`).

v2 addresses 2 Required architect findings (response-shape phantoms) + 3 Recommended cleanups (drop dead Full-HXI toggle, clarify `ProfileChatTab.threadId` precedence, match 300ms debounce precedent).

**The actual work is UI-only.** No new backend routes, no new schema columns, no new store slices. This wave RENDERS what Wave 193+194 already store and wires UX affordances (right-click menu, search, collapse, switch-thread) to existing actions/endpoints.

---

## Section 0 — Conceptual frame (carries forward from Waves 193/194)

Threads are meeting envelopes for persistent agents. The sidebar is **navigation**, not memory — it shows the operator which conversations exist, organizes them by salience (Pinned → Projects → Recents), and lets the operator switch between them. Agents themselves don't change when you switch threads; their identity, trust, episodic memory all persist. The sidebar is a Captain-facing organization aid, full stop.

HXI design principles that constrain this AD specifically:

- **#1 The system understands the human.** Sidebar surfaces what's most relevant first. Pinned threads always at top; Recents grouped by time-of-life ("Today / Yesterday / Earlier"). No mental model required.
- **#3 No emoji.** Every glyph in the sidebar is inline SVG with `strokeWidth: 1.5`, `strokeLinecap: round`, amber `#f0b060` / dim `#666680` palette.
- **#4 Motion communicates state.** Active thread highlighted (amber border-left, subtle glow). Unread threads pulse a small amber dot. No decorative motion.
- **#5 Progressive disclosure.** Sidebar is 240px expanded, 56px icon-only when collapsed. Operator-controlled via a chevron at the rail header.
- **#9 Alert-driven layout.** Threads with unread messages or pending actions float toward the top of Recents (still grouped, but bolded within their group).

---

## Section 1 — Component shape

**New file:** `ui/src/components/sidebar/ThreadSidebar.tsx`

```tsx
interface ThreadSidebarProps {
  /** When undefined, sidebar renders un-collapsed (default 240px). */
  initialCollapsed?: boolean;
  /** Called when operator picks a thread; CompactApp / FullHXI re-mount
   *  ProfileChatTab against the new thread_id. */
  onThreadSelected: (threadId: string) => void;
  /** Current active thread (drives the active-row visual). */
  activeThreadId: string | null;
}
```

The component owns:
- Local UI state: `collapsed: boolean`, `searchQuery: string`, `contextMenu: {threadId, x, y} | null`.
- Subscriptions: `useStore(s => s.chatThreads)` and `useStore(s => s.activeThreadId)`.
- Effects: on mount, hydrate via `fetch('/api/threads').then(...)`; existing `hydrateChatThreads` store action absorbs the response.
- Rendering: header → search → sections → new-chat button. ~250 LOC component, split into named sub-components within the file (`ThreadRow`, `SectionHeader`, `SidebarSearch`, `NewChatButton`, `ContextMenu`) for readability.

---

## Section 2 — Hydration on mount

On `ThreadSidebar` mount, fire one GET. **Note:** we hydrate via `/api/threads` (full list) rather than `/api/threads/recents` because the sidebar needs pinned + archived state filtering, not just last-active ordering.

```ts
useEffect(() => {
  let cancelled = false;
  void (async () => {
    try {
      const res = await fetch('/api/threads?include_archived=false&limit=100');
      if (!res.ok) return;
      const data = await res.json();   // shape: {threads: [...]}
      if (cancelled) return;
      useStore.getState().hydrateChatThreads(data.threads as AD791aChatThreadView[]);
    } catch {
      // Tier-2 honest-degrade — sidebar shows empty Pinned+Recents until next reload.
    }
  })();
  return () => { cancelled = true; };
}, []);
```

The chat handlers (AD-791a + Wave 194) already add to `chatThreads` per-turn via `setChatThread`; this hydration just seeds the map on cold-start.

---

## Section 3 — Section organization

Three sections in order (Pinned → Projects → Recents). Each is a `<SectionHeader>` + a list of `<ThreadRow>` elements.

### 3.1 Pinned

Filter: `chatThreads.values().filter(t => t.pinned && !t.archived)`. Sort by `last_active_at desc`. Always rendered (even when empty — shows a small "No pinned threads yet" line in dim text). The default Yeoman thread should appear here automatically if the operator pins it; v1 does NOT auto-pin Yeo (defer to a future AD).

### 3.2 Projects (placeholder section header only)

Renders a `<SectionHeader>` with the label "Projects" and a single dim-text line: "Coming with AD-793." This section is the placeholder slot for AD-793 (Wave 196) and lands populated then. Empty in this AD.

### 3.3 Recents

Filter: `chatThreads.values().filter(t => !t.pinned && !t.archived)`. Group by time-of-life relative to today:

```ts
function timeOfLifeGroup(lastActiveAt: number, now: number): 'today' | 'yesterday' | 'earlier' {
  const dayMs = 86_400_000;
  const startOfToday = new Date(now).setHours(0, 0, 0, 0);
  const startOfYesterday = startOfToday - dayMs;
  if (lastActiveAt >= startOfToday) return 'today';
  if (lastActiveAt >= startOfYesterday) return 'yesterday';
  return 'earlier';
}
```

Each group has a small dim text label ("Today", "Yesterday", "Earlier") and the threads in `last_active_at desc` order. Limit display to 50 threads per group (older threads accessible via search).

### 3.4 Alert-driven prominence (HXI #9)

Threads with `unread_count > 0` (a future `ChatThreadView` field — for v1, ignore until the field exists; document as a forward marker AD-792a). v1 does NOT implement unread tracking; the visual surface is reserved.

---

## Section 4 — New chat affordance

A header-level button at the top of the sidebar (or its collapsed-mode equivalent): "+ New chat".

```tsx
async function handleNewChat() {
  // Default participant: Yeoman, mirrors CompactApp's existing yeo lookup pattern.
  // CompactApp.tsx already does this — copy the same memo'd selector.
  const yeo = findYeoFromStore();
  if (!yeo) {
    // No agents loaded yet — disable button + tooltip. UI degrades silently.
    return;
  }
  const res = await fetch('/api/threads', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: yeo.callsign ?? 'New thread',
      participants: [yeo.id],
      // No project_id, no task_id, no preprompt, no model in v1.
    }),
  });
  if (!res.ok) return;
  // POST /api/threads returns `thread.to_dict()` DIRECTLY (not wrapped in {thread: ...}).
  // Verified at routers/threads.py:115-118.
  const thread = (await res.json()) as AD791aChatThreadView;
  useStore.getState().setChatThread(thread);
  useStore.getState().setActiveThread(thread.id);
  useStore.getState().setThreadForAgent(yeo.id, thread.id);
  onThreadSelected(thread.id);
}
```

The `findYeoFromStore()` helper copies the existing `yeo` memo pattern from `CompactApp.tsx` (lines 56-62). For Full HXI, default agent should be a per-Captain configured "primary agent" or fall back to Yeo if unset — but v1 always uses Yeo; per-Captain primary is a forward marker (AD-792b).

If no Yeoman agent is loaded (cold-start, agents stream still in flight), disable the button with tooltip "Loading agents…".

---

## Section 5 — Right-click context menu

A `ContextMenu` component renders on `onContextMenu` of a `ThreadRow`. Four menu items:

| Item | Action | API |
|---|---|---|
| Rename | Opens an inline text input pre-filled with current title; on Enter, sends `PATCH /api/threads/{id}` with `{title, title_locked: true}` (Wave 194 lock semantics). Esc cancels. | `PATCH /api/threads/{id}` |
| Pin / Unpin | Toggles `pinned`. `PATCH /api/threads/{id}` with `{pinned: !current}`. UI re-sorts immediately (optimistic update). | `PATCH /api/threads/{id}` |
| Archive | `PATCH /api/threads/{id}` with `{archived: true}`. Thread disappears from the sidebar; not deleted. Reversible via `GET /api/threads?include_archived=true` (out of scope for sidebar UI; manage via a future "Archived" tab). | `PATCH /api/threads/{id}` |
| Delete | Confirmation modal ("Delete this thread? Messages will be removed; episodes and agent memory are preserved."). On confirm, `DELETE /api/threads/{id}`. Cascade-to-messages handled by AD-791a; episodes are preserved (AD-791a Section 11 acceptance #7). | `DELETE /api/threads/{id}` |

Keyboard a11y: Shift+F10 opens menu on focused row. Esc closes. Arrow keys navigate menu items. Each action also has a `data-testid` for vitest.

The menu uses portal positioning (renders into `document.body`, absolute-positioned at `(event.clientX, event.clientY)`). Boundary detection: if menu would extend past viewport, anchor from the right/bottom of the click point.

---

## Section 6 — Search

A `<SidebarSearch>` input above the sections. On change (debounced **300ms** — matches the precedent at `useStore.ts:549`), fires:

```ts
const res = await fetch(`/api/threads/search?q=${encodeURIComponent(query)}`);
const data = await res.json();   // shape: {query: "...", results: [...]}
// Verified at routers/threads.py:86-95 — results, NOT threads.
const matches = data.results as AD791aChatThreadView[];
// Render matches in a flat list while searchQuery is non-empty.
```

The `/api/threads/search` endpoint already exists per AD-791 substrate (verified). When `searchQuery` is empty, sections return to normal. No client-side filtering (let the backend own search ranking; v1 ranks by `last_active_at desc` per the existing endpoint).

Empty-result state: "No threads match '<query>'." Honest-degrade when network fails: keep current sections rendered.

---

## Section 7 — Collapse mode (HXI #5 progressive disclosure)

A chevron button at the rail header toggles `collapsed`:

- **Expanded** (240px): full sidebar with sections, search, threadrows, new-chat button.
- **Collapsed** (56px): icon-only — just the new-chat button + first-letter avatars of pinned threads (vertical column). Click an avatar = open that thread. Right-click = same context menu.

Persisted to localStorage under key `probos.sidebar.collapsed` so the operator's preference survives reload. CompactApp passes the persisted value as `initialCollapsed` prop.

---

## Section 8 — Hosting

### CompactApp.tsx

Add `ThreadSidebar` to the left of the existing `ProfileChatTab`. Replace the current full-width `ProfileChatTab` mount with:

```tsx
<div style={{ display: 'flex', height: '100vh' }}>
  <ThreadSidebar
    initialCollapsed={loadSidebarCollapsed()}
    onThreadSelected={(threadId) => useStore.getState().setActiveThread(threadId)}
    activeThreadId={useStore((s) => s.activeThreadId)}
  />
  <div style={{ flex: 1, minWidth: 0 }}>
    <ProfileChatTab agentId={derivedAgentId} threadId={activeThreadId ?? undefined} />
  </div>
</div>
```

The `derivedAgentId` is resolved from the active thread's `participants[0]` (single-participant 1:1 threads — v1). If `activeThreadId` is null (cold-start), fall back to Yeoman as today.

**`ProfileChatTab` must accept an optional `threadId` prop** to mount against an explicit thread instead of always defaulting to the agent's implicit default thread. ~10 line change:

- Add `threadId?: string` to props.
- Effective thread resolution: `effectiveThreadId = props.threadId ?? threadIdByAgent.get(agentId) ?? undefined`. **Prop wins** when set.
- Pass `effectiveThreadId` as `req.thread_id` on chat fetch body (the back-compat shim at `routers/agents.py:agent_chat` Section 5.5 already accepts it).
- On server response, `setThreadForAgent(agentId, data.thread_id)` is still called — idempotent when the response's `thread_id` matches the prop. If the response's `thread_id` *differs* from the prop (server-side route mismatch / explicit reassignment), the response is authoritative; log at info level and update the store. This preserves the AD-791a invariant that the store holds the latest server-confirmed thread.
- When `props.threadId` is null/undefined, behavior is unchanged (existing default-thread path).

### Full HXI

Deferred entirely to AD-792c forward marker. Wave 195 ships zero Full-HXI changes — no toggle, no settings field, no dead code. The canvas-first Full HXI experience is unchanged. AD-792c will own the integration design (layout, panel z-ordering, alert-layout interactions) when it lands.

---

## Section 9 — Tests

### Vitest (6 minimum; spec aims for 9-10)

1. `ThreadSidebar.render.test.tsx` — sidebar renders Pinned + Projects-placeholder + Recents + New-chat + Search on cold-start with mocked chatThreads.
2. `ThreadSidebar.hydrate.test.tsx` — mount fires `GET /api/threads`; `hydrateChatThreads` action invoked with response.
3. `ThreadSidebar.search.test.tsx` — typing in search input fires debounced `/api/threads/search`; results replace sections while query non-empty; clears restores sections.
4. `ThreadSidebar.recents-grouping.test.tsx` — given threads with various `last_active_at` timestamps, assert correct Today/Yesterday/Earlier bucket placement.
5. `ThreadSidebar.contextMenu.test.tsx` — right-click ThreadRow renders menu; Rename / Pin / Archive / Delete each fire the corresponding API + store action.
6. `ThreadSidebar.collapse.test.tsx` — chevron toggles collapsed; localStorage persists; collapsed view renders icon-only column.
7. `ThreadSidebar.newChat.test.tsx` — click "New chat" POSTs to `/api/threads` with Yeoman as participant; `setActiveThread` invoked with new thread id; `onThreadSelected` callback fires.
8. `ThreadSidebar.activeRow.test.tsx` — active thread row has the amber border-left + glow; other rows do not.
9. `ProfileChatTab.threadId-prop.test.tsx` — passing `threadId` prop causes chat requests to send `req.thread_id`; absence preserves default-thread behavior (regression test for back-compat).
10. `CompactApp.sidebar-integration.test.tsx` — Compact mounts the sidebar alongside ProfileChatTab; switching threads via sidebar re-mounts the chat panel.

### No pytest required

Pure UI feature. All backend endpoints already exist + are tested by AD-791a/AD-794/AD-809 suites.

---

## Section 10 — Non-goals (Do NOT build)

- ❌ AD-793 Projects table or system-context injection (separate wave).
- ❌ Unread tracking on threads (no `unread_count` field exists today; AD-792a forward marker).
- ❌ Per-Captain primary-agent preference for "New chat" (AD-792b forward marker — always Yeo in v1).
- ❌ Full HXI sidebar layout integration (AD-792c forward marker — toggle exists, render does not in Full HXI).
- ❌ Drag-to-reorder pinned threads (forward marker AD-792d).
- ❌ Multi-select for batch archive/delete (forward marker).
- ❌ "Archived" tab / archived-thread browsing UI (forward marker).
- ❌ Thread sharing / export (forward marker).
- ❌ Changes to backend endpoints or schema.
- ❌ Changes to layer architecture beyond UI components.

---

## Section 11 — Acceptance criteria

1. `ThreadSidebar.tsx` exists at `ui/src/components/sidebar/ThreadSidebar.tsx`.
2. `CompactApp.tsx` renders the sidebar alongside `ProfileChatTab` (sidebar left, chat right). Existing Yeo / starter chips / greeting flow is preserved when no active thread is selected.
3. On mount, sidebar fires `GET /api/threads?include_archived=false&limit=100` and populates `chatThreads` store via `hydrateChatThreads`. Response shape: `{threads: [...]}`.
4. Pinned section renders pinned threads first (sorted by `last_active_at desc`); Projects renders the placeholder header; Recents groups threads by Today / Yesterday / Earlier.
5. "+ New chat" button POSTs to `/api/threads` with Yeoman as default participant; the endpoint returns `thread.to_dict()` directly (NOT wrapped); on success, the new thread becomes active and `ProfileChatTab` re-mounts.
6. Right-click on a thread row renders the context menu with Rename / Pin / Archive / Delete; each item fires the correct API + store update.
7. Rename writes `title_locked: true` via the existing PATCH endpoint (Wave 194 contract).
8. Search input debounces **300ms** (matches `useStore.ts:549` precedent); fires `GET /api/threads/search?q=...`; response shape is `{query, results}`; results replace sections during search; clear restores sections.
9. Collapse chevron toggles 240px ↔ 56px; localStorage persists across reload.
10. `ProfileChatTab.threadId` prop exists with explicit precedence: `props.threadId ?? threadIdByAgent.get(agentId)`. Default behavior unchanged when unset. When server response carries a different `thread_id` than the prop, response wins and `setThreadForAgent` is called (AD-791a invariant preserved).
11. Full HXI is NOT modified in this wave (no toggle, no settings, no render). AD-792c forward marker owns that integration.
12. 6+ vitest added (spec aims for 9-10). All existing tests still pass. `npm run build` clean.
13. No backend changes; no new pip / npm deps.
14. Trackers updated: PROGRESS.md prepends a Wave 195 entry; roadmap.md marks AD-792 SHIPPED Wave 195; GH issue #716 closed with commit hash + acceptance summary.
15. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Section 12 — File touchpoints

| File | Change |
|---|---|
| `ui/src/components/sidebar/ThreadSidebar.tsx` | NEW. ~250 LOC primary component + sub-components. |
| `ui/src/components/sidebar/threadGrouping.ts` | NEW helper for `timeOfLifeGroup()` (testable independently). |
| `ui/src/components/sidebar/threadApi.ts` | NEW thin wrappers for `GET /api/threads`, `POST /api/threads`, `PATCH /api/threads/{id}`, `DELETE /api/threads/{id}`, `GET /api/threads/search?q=...`. Keeps fetch logic out of the React component. |
| `ui/src/CompactApp.tsx` | Wrap existing `ProfileChatTab` with a flex container; render `ThreadSidebar` to the left. Resolve `derivedAgentId` from active thread or fall back to Yeo. |
| `ui/src/components/profile/ProfileChatTab.tsx` | Add optional `threadId?: string` prop; when set, include `thread_id: this.props.threadId` in chat fetch body. Otherwise behavior unchanged. |
| `ui/src/store/useStore.ts` | No new slices needed. `hydrateChatThreads` and `setChatThread` already exist (Wave 193 + 194). **Do NOT add `pinnedThreadIds()` / `recentThreadIds()` selectors** — inline filtering in the component is clearer for v1 and scope-bounded. |
| `ui/src/__tests__/ThreadSidebar.render.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ThreadSidebar.hydrate.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ThreadSidebar.search.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ThreadSidebar.recents-grouping.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ThreadSidebar.contextMenu.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ThreadSidebar.collapse.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ThreadSidebar.newChat.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ThreadSidebar.activeRow.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ProfileChatTab.threadId-prop.test.tsx` | NEW vitest. |
| `ui/src/__tests__/CompactApp.sidebar-integration.test.tsx` | NEW vitest. |

---

## Section 13 — Estimated scope

~400-500 LOC raw (UI + tests). ~14 files touched. One Builder commit. **Single Builder dispatch.**

---

## Section 14 — Forward markers (carried + new)

- **AD-792a** — Unread tracking (`unread_count` field on `ChatThread`, server-side `last_read_at` per-thread per-Captain, sidebar pulse on unread).
- **AD-792b** — Per-Captain primary-agent preference for "New chat" default participant (replace v1's hardcoded Yeoman).
- **AD-792c** — Full HXI sidebar layout integration (layout, panel z-ordering, alert-layout interactions).
- **AD-792d** — Drag-to-reorder pinned threads.
- **AD-792e** — Archived thread browsing UI ("Archived" tab or filter).
- **AD-792f** — Thread sharing / export (`POST /api/threads/{id}/share`, `GET /api/threads/{id}/export` — backend AD).

---

## Section 15 — Verify-first audit checklist (Builder pre-flight)

```
grep -n "@router\." src/probos/routers/threads.py
    → Expected: GET /, GET /search, GET /recents, POST /, GET/PATCH/DELETE /{id},
      GET/POST /{id}/messages, POST /{id}/auto-name, POST /{id}/promote-to-task.
      All endpoints needed by AD-792 exist.

grep -n "chatThreads\|hydrateChatThreads\|setChatThread\|setActiveThread\|threadIdByAgent" ui/src/store/useStore.ts
    → Expected: hydration + actions already defined at L297-410 and L1034-1044.

grep -n "callsign === 'Yeo'" ui/src/CompactApp.tsx
    → Expected: existing yeo lookup pattern at L~57; sidebar reuses this.

grep -n "AD791aChatThreadView" ui/src/store/useStore.ts
    → Expected: type definition with id, title, participants[], pinned, archived, last_active_at fields.

grep -n "interface.*Props\|export function ProfileChatTab" ui/src/components/profile/ProfileChatTab.tsx
    → Expected: existing props interface; AD-792 adds optional threadId field.

grep "GET\|POST\|PATCH\|DELETE" src/probos/routers/threads.py | wc -l
    → Confirm endpoint count matches what threadApi.ts wrappers will call.

read ui/src/CompactApp.tsx in full
    → Confirm overall structure: WebSocket setup, yeo lookup, ProfileChatTab mount, greeting/chips flow.
      Sidebar integrates without disrupting these.

read ui/src/components/profile/ProfileChatTab.tsx around the agent_id resolution + chat fetch site
    → Identify where `req.thread_id` should be passed (AD-791a wiring already accepts it).
```

If any of these don't match, stop and report.
