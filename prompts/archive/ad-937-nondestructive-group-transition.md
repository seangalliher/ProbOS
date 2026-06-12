# AD-937 — Teams-style non-destructive 1:1 → group transition (fixes the unreachable-1:1 regression)

**Target repo:** OSS (`d:\ProbOS`). **Provisional AD = AD-937** (assign sequentially at build — after AD-935
reactivity, AD-936 chat-message-metadata UI). Captain-reported live.
**Status: SPEC — needs Architect verify-first pass before a Builder dispatch** (frontend wiring below is
described at the behavior level; exact prop/store signatures must be grepped against HEAD first).

## The bug (verified vs HEAD) — TWO layers
Adding a person to a 1:1 chat **destroys the 1:1** AND clobbers its addressing, so the Captain can no longer
return to a 1:1 with that agent (reopening the profile shows the group again).

**Layer 1 — destructive backend mutation:** AD-917 `GroupChatHeader.handleAdd` (ui/.../profile/GroupChatHeader.tsx:59)
calls `addParticipant(threadId, agentId)` → `ChatThreadStore.add_participant` (src/probos/threads/__init__.py:435)
is an in-place read-modify-write that rewrites the SAME row `participants ["a"] → ["a","b"]`. The 1:1 row is
repurposed INTO the group. (AD-932 `EmptyChatAddPeople` materializes the 1:1 then hands off to this picker.)

**Layer 2 — addressing collision (the reason the 1:1 is unreachable even after a non-destructive create):**
`threadIdByAgent` (useStore.ts:336) is a SINGLE slot per agent. Group-open binds the group INTO the host's
slot: `ChatsPanel.handleOpen` (ui/.../chats/ChatsPanel.tsx:104) does `setThreadForAgent(host, thread.id)` then
`openAgentProfile(host)`; `NewChatModal` 2+ branch (ui/.../chats/NewChatModal.tsx:52-54) does the same. So
`threadIdByAgent[host] = groupId`. `ProfileChatTab` resolves `effectiveThreadId = props.threadId ??
threadIdByAgent.get(agentId)` — so opening the host's profile (roster click → `openAgentProfile(host)`, NO
threadId prop) now resolves to the GROUP, not the 1:1. **The group hijacked the agent's 1:1 slot.**

## The Teams model (target — confirmed by the Captain's screenshots)
On a **1:1**, "add people" prompts for a **group name**, then creates a **NEW** group chat instance and
**leaves the original 1:1 intact**. On an **existing group**, "add people" adds to that group (mutation is
correct there — matches Teams). So the behavior branches on the current thread's shape:
- **current thread is a 1:1** (single crew participant / `is_default`): "add people" → name prompt →
  `createThread({title: groupName, participants: [agentId, ...pickedIds]})` (a SEPARATE new row) → switch the
  view to the new group. The 1:1 row (`participants=[agentId]`, `is_default`) is **never mutated**.
- **current thread is a group** (≥2 crew): keep the existing `addParticipant` mutate path (correct).

This is non-destructive and **fixes the regression as a consequence**: the agent's 1:1 persists, so reopening
the profile resolves back to it. The AD-931 `NewChatModal` already implements exactly this create-new pattern
(1 agent → DM, 2+ → `createThread` group) — **reuse it**, do not invent a parallel path.

## Required behavior / acceptance
1. **Non-destructive add on a 1:1.** Adding people to a 1:1 creates a new named group thread; the original
   1:1 thread row is unchanged (`participants` still `[agentId]`, `is_default` still set).
2. **1:1 stays reachable.** After adding people + closing the chat, reopening the agent's profile shows the
   **1:1**, not the group. (This is the Captain's exact repro — make it a test.)
3. **Name prompt.** The add-people flow on a 1:1 surfaces a group-name input before creating (Teams parity);
   reuse the AD-931 `NewChatModal` name field + picker.
4. **Group add still mutates.** Adding a person to an already-group thread still uses `addParticipant`.
5. **Recovery for already-mutated bindings.** If `threadIdByAgent[agentId]` currently points at a group
   (from the old destructive flow), opening the agent's profile must re-resolve to the agent's **default 1:1**
   (the `is_default` / `participants=[agentId]` thread), not the stale group binding. Net rule: the
   per-agent 1:1 binding must never resolve to a group thread.
6. **Defense in depth (backend, optional but recommended):** `ChatThreadStore.add_participant` should refuse
   to mutate a thread whose `metadata.is_default` is true (return the thread unchanged + log a warning), so no
   future code path can destroy a default 1:1 by adding a participant. If added, cover with a pytest.

## Validated fix (frontend-only, two parts)

### Part A — non-destructive create on a 1:1 (fixes Layer 1)
Branch the add-people flow on the current thread's shape (reuse `chatFilters.crewParticipantIds`,
ui/.../chats/chatFilters.ts:27):
- **1:1** (`crewParticipantIds(thread).length <= 1`, or the AD-932 empty/materialized 1:1): "add people"
  opens `NewChatModal` **pre-seeded with the host agent** (a locked first participant). On confirm with 2+,
  NewChatModal's existing 2+ branch `createThread({title, participants})` mints a SEPARATE new group row —
  the 1:1 row is NEVER mutated. Extend `NewChatModal` with an optional prop
  `seedParticipantId?: string` that pre-populates `selected=[seedParticipantId]` and renders it non-removable.
- **Group** (`>= 2` crew): keep the inline `GroupChatHeader` → `AddParticipantPopover` → `addParticipant`
  mutate path (correct — matches Teams).

Rewire the AD-932 `EmptyChatAddPeople` button: instead of `createThread([agentId]) + setChatThread +
setThreadForAgent` (materialize-then-mutate), it opens `NewChatModal` seeded with `agentId`. (The 1:1 itself
is created lazily by the server `get_or_create_default_for_agent` on first message — unchanged.)

### Part B — stop groups hijacking the agent's 1:1 slot (fixes Layer 2)
Add a dedicated group-thread override so group addressing never overwrites `threadIdByAgent`:
- **useStore.ts:** add `activeProfileThreadId: string | null` (default null); add
  `openGroupChatThread(hostId: string, threadId: string)` = `set({ activeProfileThreadId: threadId,
  activeProfileAgent: hostId, ...the existing openAgentProfile body })`; in `openAgentProfile` (:954) ALSO set
  `activeProfileThreadId: null` (a roster/1:1 open clears any group override).
- **ProfileChatTab.tsx:** resolve `effectiveThreadId = props.threadId ?? activeProfileThreadId ??
  threadIdByAgent.get(agentId)` (read `activeProfileThreadId` from the store). For a group, `activeProfileThreadId`
  = groupId; for a 1:1, it's null → falls to the agent's 1:1 default. Groups no longer touch `threadIdByAgent`.
- **ChatsPanel.handleOpen (:102-105)** and **NewChatModal 2+ branch (:52-54):** replace
  `setThreadForAgent(host, thread.id); openAgentProfile(host)` with `openGroupChatThread(host, thread.id)`.
- The new 1:1→group flow (Part A) opens the created group via `openGroupChatThread(host, newGroupId)` too.

Net: a group is addressed by `activeProfileThreadId`; an agent's `threadIdByAgent` slot is reserved for its
1:1. Reopening an agent's profile from the roster (`openAgentProfile`) clears the override → shows the 1:1.
The 1:1 row persists (Part A) so it resolves. Both Captain requirements satisfied.

Backend `add_participant` is-default guard = forward marker **AD-937a** (frontend fix is sufficient; the guard
is defense-in-depth, and 1:1 detection by `is_default` is imperfect since client `createThread([id])` omits it).

## Tests — Vitest, floor +10 (+ `npm run build` clean)
Mirror the AD-931/AD-932 test idioms (real store via `useStore.setState`, mock `threadApi.createThread`/
`addParticipant`, BF-287). Prefer testing the store actions + the small flow handlers; if full-component
render is heavy, follow the `groupsend`/`bf294b` component-isolation precedent.
1. **`openGroupChatThread` sets the override, NOT `threadIdByAgent`** — after the call, `activeProfileThreadId
   === groupId` and `threadIdByAgent.get(host)` is UNCHANGED.
2. **`openAgentProfile` clears the override** — after `openGroupChatThread(host, g)` then
   `openAgentProfile(host)`, `activeProfileThreadId === null`.
3. **ProfileChatTab resolution priority** — `props.threadId ?? activeProfileThreadId ?? threadIdByAgent.get`
   (unit-test the resolver: override wins when set; falls to `threadIdByAgent` when null).
4. **Reopen-1:1 repro (the Captain's bug, headline test)** — seed `threadIdByAgent[ezri]=oneToOneId`;
   `openGroupChatThread(ezri, groupId)` (view shows group); then `openAgentProfile(ezri)`; assert the resolved
   thread is `oneToOneId` (the 1:1), NOT `groupId`.
5. **Add-people on a 1:1 opens NewChatModal seeded, does NOT mutate** — the 1:1 add entry opens `NewChatModal`
   with `seedParticipantId=host`; `addParticipant` is NOT called.
6. **NewChatModal seed** — `seedParticipantId` pre-populates `selected=[seed]` and the seed chip is
   non-removable (no remove control / remove is a no-op).
7. **NewChatModal 2+ creates a new group + opens via override** — confirm with seed+1 → `createThread` called
   once with both participants; `openGroupChatThread` called (NOT `setThreadForAgent`).
8. **Add-people on a group still mutates** — `GroupChatHeader` add on a ≥2-crew thread still calls
   `addParticipant` (unchanged).
9. **ChatsPanel.handleOpen uses the override** — opening a group from the CHATS list calls
   `openGroupChatThread`, not `setThreadForAgent`.
10. **No-emoji guard** (`/\p{Extended_Pictographic}/u`) on any new/changed component source.

Update the AD-919/AD-931/AD-932 tests that assert the old `setThreadForAgent`+`openAgentProfile` group-open
or the AD-932 materialize-then-mutate flow (obsolete-contract updates — the same pattern used across
AD-933a/933b/934). Grep for `setThreadForAgent` in `ui/src/**/__tests__` and update the group-open
assertions to `openGroupChatThread`.

## Gates
- `cd d:\ProbOS\ui; npx vitest run` (full suite; report pass/skip vs baseline; zero regressions).
- `cd d:\ProbOS\ui; npm run build` (tsc -b + vite) — clean.
- No backend change → no pytest.

## Acceptance
- Adding people to a 1:1 creates a SEPARATE new group (`createThread`), never mutates the 1:1 row.
- After creating the group + closing it, reopening the agent's profile resolves to the **1:1** (headline
  repro test #4 green).
- Adding to an existing group still uses `addParticipant`. `npm run build` clean. Engineering-Principles
  compliance verified.

## Do NOT (scope fence)
- Do NOT remove the ability to add to an existing group (that path stays `addParticipant`).
- Do NOT change `ChatThreadStore.add_participant` or any backend (the is-default guard is forward marker
  **AD-937a**); no pytest. Do NOT add an explicit custom group-name input (NewChatModal auto-titles from
  callsigns; explicit-name is forward marker **AD-937b**).
- Do NOT touch the AD-933/933a/933b/934/935 pipeline, the facilitator, the Ward Room, `IntentMessage`, or
  `Glyphs.tsx`.
- No push. Explicit-path stage (NOT `git add -A`); deletion-audit before commit.

## Trackers (after gates green)
- `docs/development/roadmap.md`: AD-937 row, SHIPPED + 2026-06-08 + gate note.
- `PROGRESS.md`: prepend an AD-937 block.
- `DECISIONS.md` (match where AD-934 went): AD-937 entry — the two-layer bug (destructive `add_participant`
  mutation + `threadIdByAgent` slot collision), the fix (non-destructive `createThread` + `activeProfileThreadId`
  override so groups stop hijacking the agent's 1:1 slot), forward markers AD-937a (backend is-default guard),
  AD-937b (explicit group-name input).
