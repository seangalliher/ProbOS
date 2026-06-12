# AD-938 — Group chat shows the real thread transcript (hydrate-on-open + thread-keyed messages)

**Target repo:** OSS (`d:\ProbOS`). **This AD = AD-938.** Highest committed+pushed: AD-937 (`92d4fad1`).
**Mode:** Builder. **Frontend only.** Vitest + `npm run build`. Commit local. No push.

## Problem (Captain-reported, diagnosed by code + LIVE repro)
Opening a group chat (e.g. "Ezri, Yeo") from the CHATS list opens the host agent's profile with an **empty
transcript and NO group header** (no participant chips, no meeting toggle), and adding people to a 1:1 then
opening the new group shows the same broken 1:1-looking view. TWO verified root causes:

1. **The opened group thread is never hydrated into `chatThreads`.** `ChatsPanel.handleOpen`
   (`ui/src/components/chats/ChatsPanel.tsx:98`) calls `openGroupChatThread(host, thread.id)` but never
   `setChatThread(thread)` — even though it HAS the `thread` object. So `chatThreads.get(groupId)` is
   `undefined`, and everything that reads it breaks: `GroupChatHeader` (`if (!thread) return null`,
   mounted at `ProfileChatTab.tsx:859`), the `meetingActive` selector (`ProfileChatTab.tsx:~502`,
   reads `chatThreads.get(activeThreadId)?.metadata.meeting_active`), and `MeetingView`'s participant list.
2. **The transcript renders the per-AGENT buffer, not the thread's messages.** `ProfileChatTab.tsx:131`
   `conversation = agentConversations.get(agentId)`, `:484` `messages = conversation?.messages`. The only
   history load is `fetch('/api/agent/${agentId}/chat/history')` (`:535`) — the agent's 1:1 history. The group
   thread's messages are NEVER fetched (no `GET /api/threads/{id}/messages` on open). So a group always shows
   the HOST agent's 1:1 buffer. `activeThreadId` (AD-937 `resolveProfileThreadId`) is correct for the SEND
   target + meeting flag, but the DISPLAYED transcript ignores it.

Backend is correct and unchanged (`GET /api/threads/{id}/messages` returns `{thread_id, messages:[...]}`,
each `{id, thread_id, author_id, role, body, created_at, metadata}` — verified `threads/__init__.py:140`).

## Fix — two parts, frontend only

### Part 1 — hydrate the thread into `chatThreads` on every open path
`setChatThread(thread)` already exists (`useStore.ts:1278`). Call it wherever a group/thread is opened so
`GroupChatHeader`/`MeetingView`/`meetingActive` resolve:
- **`ChatsPanel.handleOpen` (`ChatsPanel.tsx:98`)**: before `openGroupChatThread(host, thread.id)`, call
  `setChatThread(thread)` (the function already has `thread`). Add `const setChatThread = useStore(s => s.setChatThread)`.
- **`NewChatModal` 2+ branch (`NewChatModal.tsx:~52`)**: after `createThread(...)` returns `thread`, call
  `setChatThread(thread)` before `openGroupChatThread(thread...)`. (The created group must be hydrated so its
  header/participants show immediately.)
- **`ChatsPanel.handleJoin`** already calls `handleOpen(updated ?? thread)` — covered once `handleOpen`
  hydrates.

### Part 2 — thread-keyed transcript (display the thread's real messages)
**A. `ui/src/components/sidebar/threadApi.ts` — add a messages-list wrapper** (mirror `listThreads` shape):
```typescript
export interface ThreadMessageDTO {
  id: string; thread_id: string; author_id: string; role: string;
  body: string; created_at: number; metadata?: Record<string, unknown> | null;
}
/** GET /api/threads/{id}/messages -> {thread_id, messages: [...]}. Tier-2: [] on failure. */
export async function listMessages(threadId: string, limit = 200): Promise<ThreadMessageDTO[]> {
  try {
    const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}/messages?limit=${limit}`);
    if (!res.ok) return [];
    const data = (await res.json()) as { messages?: ThreadMessageDTO[] };
    return Array.isArray(data?.messages) ? data.messages : [];
  } catch { return []; }
}
```

**B. `ui/src/store/useStore.ts` — a thread-message display slice** (additive; mirrors the `chatThreads` Map
pattern):
- State: `threadMessages: Map<string, AgentProfileMessage[]>` (init `new Map()`), declared in the interface
  next to `chatThreads`.
- `setThreadMessages(threadId: string, msgs: AgentProfileMessage[])` — `next = new Map(...); next.set(id, msgs); set({threadMessages: next})`.
- `appendThreadMessage(threadId: string, msg: AgentProfileMessage)` — append to the existing array (cap to
  last 200, mirror `addAgentMessage`'s `.slice(-99)` idiom but 200).

**C. `ui/src/components/profile/ProfileChatTab.tsx` — load + display thread messages when a thread is active**
- Add a mapper (module scope): `threadDtoToMessage(m: ThreadMessageDTO, agents): AgentProfileMessage` →
  `{ id: m.id, role: m.role === 'captain' ? 'user' : (m.role === 'agent' ? 'agent' : 'system'),
  text: m.body, timestamp: m.created_at, authorId: m.role === 'agent' ? m.author_id : undefined,
  callsign: m.role === 'agent' ? (agents.get(m.author_id)?.callsign ?? undefined) : undefined }`.
  (Captain messages → `role:'user'`, no avatar; agent → `role:'agent'` with author avatar via AD-936
  `ChatMessageRow`; system → unchanged.)
- A `useEffect` keyed on `[activeThreadId]`: when `activeThreadId` is set, `listMessages(activeThreadId)` →
  map → `setThreadMessages(activeThreadId, mapped)`. (Tier-2: the wrapper already degrades to `[].)
- **Display source switch:** replace `const messages = conversation?.messages ?? []` (`:484`) with:
  `const threadMsgs = useStore(s => activeThreadId ? s.threadMessages.get(activeThreadId) : undefined);`
  `const messages = activeThreadId ? (threadMsgs ?? []) : (conversation?.messages ?? []);`
  So: thread context → thread messages (the real group/1:1 transcript); no thread (cold 1:1 before first
  send) → the per-agent buffer (unchanged behavior).
- **Send-path reconcile (keep the optimistic UX):** in the send handler (`~:617-716`), when `activeThreadId`
  is set, ALSO write the optimistic Captain message + the reply/`per_agent_replies` to
  `appendThreadMessage(activeThreadId, ...)` (in addition to the existing `addAgentMessage` calls, which stay
  for the no-thread path). For the group branch (`per_agent_replies`), append each reply as
  `{id: crypto.randomUUID-ish, role:'agent', text, timestamp: Date.now()/1000, authorId: r.agent_id, callsign: r.callsign}`
  (DROP the `callsign:` text prefix — the AD-936 avatar+label already shows the author). For the 1:1 branch,
  append the single agent reply with `authorId: agentId`.
- Mention `activeThreadId` must be a dependency where the effect/selectors read it.

Notes:
- `AgentProfileMessage` already has optional `authorId`/`callsign` (AD-936). `ChatMessageRow` renders avatar +
  `HH:MM` per author. So thread messages render correctly with per-author avatars + timestamps — this is the
  Teams-style transcript the Captain wants.
- Do NOT remove `agentConversations`/`addAgentMessage` (still the no-thread cold-1:1 path + the cross-session
  `/chat/history` seed). This is additive.

## Tests — Vitest, floor +10 (+ `npm run build` clean)
Mirror the existing `ProfileChatTab.*`/`ChatsPanel.*` idioms (real store via `useStore.setState`,
mock `threadApi`, BF-287). Prefer testing the new pure mapper + store actions + a small extracted handler;
if full-`ProfileChatTab` render is too heavy (the `groupsend`/`bf294b` precedent), test the data path.
1. `listMessages` returns mapped array on `{messages:[...]}`, `[]` on `!ok`/throw.
2. `threadDtoToMessage`: captain→`user`/no authorId; agent→`agent`+authorId+resolved callsign; system→`system`.
3. `setThreadMessages`/`appendThreadMessage` store actions (set, append, 200-cap).
4. **Hydrate-on-open**: `ChatsPanel.handleOpen` on a group calls `setChatThread(thread)` AND
   `openGroupChatThread(host, id)` (spy both).
5. **NewChatModal 2+** calls `setChatThread(createdThread)` before `openGroupChatThread`.
6. **Display switch**: with `activeThreadId` set + `threadMessages` seeded, the rendered transcript shows the
   THREAD messages (assert a thread message's text/author), NOT `agentConversations`. With no `activeThreadId`,
   it shows `agentConversations` (unchanged).
7. **Group transcript shows per-author avatars**: two thread messages from different agents → two distinct
   `AgentAvatarBadge`s (reuse the AD-936 assertion).
8. **Effect loads on activeThreadId change**: changing `activeThreadId` triggers `listMessages` + `setThreadMessages`.
9. **Send reconcile (group)**: a group send appends the Captain msg + each `per_agent_reply` to
   `threadMessages[activeThreadId]` (no `callsign:` prefix in the text).
10. No-emoji guard on any new/changed component source.

Also run the FULL suite — Part 2's display switch touches the core render path; update any obsolete
`ProfileChatTab`/`groupsend` assertions that asserted the per-agent buffer for a thread-context message
(obsolete-contract updates, the established pattern).

## Gates (report exact counts)
- `cd d:\ProbOS\ui; npx vitest run` (FULL suite — report pass/skip vs the AD-937 baseline 1289; zero regressions).
- `cd d:\ProbOS\ui; npm run build` (tsc -b + vite) — clean.
- No backend change → no pytest.

## Acceptance
- Opening a group from CHATS shows the GroupChatHeader (participants + meeting toggle) AND the group's real
  message transcript with per-author avatars + timestamps; the meeting toggle works (thread hydrated).
- Adding people to a 1:1 then opening the new group shows the group's transcript, not a 1:1.
- A cold 1:1 (no thread yet) still shows the per-agent buffer (unchanged). `npm run build` clean.
- Verify Engineering-Principles compliance (`.github/copilot-instructions.md`).

## Do NOT (scope fence)
- No backend / REST / pytest (the `GET /messages` endpoint already exists). No WebSocket/poll for live
  push (that is **AD-935a**; this AD loads on open + reconciles on send, which is enough for the
  synchronous-cascade model). No `Glyphs.tsx`/`AgentAvatarBadge` change. No removal of `agentConversations`.
- Do NOT touch the AD-933/933a/933b/934/935 pipeline, the facilitator, the Ward Room, `IntentMessage`, or the
  MeetingView Captain slot (that is the sibling **AD-939**) / draggable panel (**AD-940**) / Playwright
  harness (**AD-941**) — those are separate ADs in this wave.
- No push. Stage explicit paths (NOT `git add -A`); deletion-audit before commit.

## Trackers (after gates green)
- `docs/development/roadmap.md`: AD-938 row, SHIPPED + 2026-06-09 + gate note.
- `PROGRESS.md`: prepend an AD-938 block.
- `DECISIONS.md` (match where AD-937 went): AD-938 entry — the two root causes (unhydrated thread + per-agent
  transcript), the fix (hydrate-on-open + thread-keyed `threadMessages` slice + `listMessages` + send
  reconcile), forward markers AD-935a (live WS push), AD-938a (paginate/scrollback for long threads).
