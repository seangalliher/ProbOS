# AD-932: Discoverable "add people" on an empty/fresh 1:1 chat

**Status:** Ready to build (frontend-only)
**Dependencies:** AD-917 (`GroupChatHeader` + `AddParticipantPopover`), AD-791a (`createThread`, the per-agent default 1:1 thread, `setThreadForAgent`/`setChatThread`). **Independent of AD-931** — builds on AD-917/threadApi; can land before or after AD-931.
**Estimated tests:** **+8 Vitest floor** in one new file (`EmptyChatAddPeople.test.tsx`). **NO pytest** — endpoints already exist. **Do NOT full-render `ProfileChatTab`** (see Decision C).
**Highest committed AD:** **AD-930** (pushed). AD-931 / AD-932 are **unused**.
**Commit policy:** **COMMIT LOCAL ONLY. DO NOT PUSH.** The Captain decides when to push.

---

## One-line

On a **fresh 1:1 chat that has no thread yet**, render a discoverable **"+ Add people"** affordance that **materializes the 1:1 thread** (`createThread([agentId])`) so the existing AD-917 `GroupChatHeader` + `AddParticipantPopover` take over — turning the 1:1 into a group. **No `GroupChatHeader` contract change, no backend, no Ward Room.**

---

## Problem (verified against HEAD)

`ProfileChatTab` mounts the in-chat group controls **only once a thread exists**:

```
ProfileChatTab.tsx:483   const activeThreadId = useStore((s) => threadId ?? s.threadIdByAgent.get(agentId));
ProfileChatTab.tsx:834   {activeThreadId && <GroupChatHeader threadId={activeThreadId} />}
```

`GroupChatHeader` itself early-returns when there is no thread:

```
GroupChatHeader.tsx:33   if (!thread) return null;
```

A **brand-new 1:1** has **no thread until the first message is sent** (the row is created server-side by `get_or_create_default_for_agent` on the first `agent_chat` turn). So on an empty 1:1: `activeThreadId` is `undefined` → `GroupChatHeader` is not mounted → there is **no add-participant control at all**. The only way to "add someone" is to first send a message, then find the thin header bar — **undiscoverable**, exactly the Captain's observation #2.

---

## Decision (what this builds, and why)

### A. A small `EmptyChatAddPeople` affordance that *materializes* the thread

Add a focused component `ui/src/components/profile/EmptyChatAddPeople.tsx`, mounted by `ProfileChatTab` **only when there is no active thread**. On click it creates the 1:1 thread, writes it into the store, and points the agent at it — which makes `activeThreadId` resolve, so the **existing** `GroupChatHeader` (and its `AddParticipantPopover`) mounts on the next render. The Captain then clicks the header's existing add-participant button to pick the second crew member, converting the 1:1 into a group.

```ts
export function EmptyChatAddPeople({ agentId }: { agentId: string }) {
  const agent = useStore((s) => s.agents.get(agentId));
  const setChatThread = useStore((s) => s.setChatThread);
  const setThreadForAgent = useStore((s) => s.setThreadForAgent);

  // Only a crew 1:1 can become a group. Non-crew / unknown host → nothing.
  if (!agent?.isCrew) return null;

  async function handleAddPeople() {
    // Materialize the 1:1 thread so GroupChatHeader (+ its picker) can mount.
    const t = await createThread({ title: agent.callsign, participants: [agentId] });
    if (!t) return; // Tier-2 honest-degrade: createThread null → keep the button, no store write
    setChatThread(t);              // GroupChatHeader reads chatThreads.get(threadId)
    setThreadForAgent(agentId, t.id); // → activeThreadId resolves → header mounts
  }

  return (
    <button data-testid="empty-chat-add-people" onClick={() => { void handleAddPeople(); }} …>
      <UserPlus size={14} /> Add people
    </button>
  );
}
```

**Why materialize via `createThread` (not reuse a hidden default):** there is no client-callable "get-or-create my 1:1 thread" endpoint — `get_or_create_default_for_agent` is only invoked server-side by the `agent_chat` message path. When `ProfileChatTab` shows the empty state, the client genuinely has **no** thread for this agent (`threadId` prop undefined **and** `threadIdByAgent.get(agentId)` empty — that is the exact gate for rendering this button). `createThread([agentId])` is the correct client-side materialization. The thread it creates (`participants=[agentId]`, `project_id=NULL`) is also what the server's default lookup matches, so it doubles as the agent's 1:1 default.

> **Known minor edge (Tier-2, acceptable):** if a server-side 1:1 default already exists but the client never hydrated it, `createThread([agentId])` mints a second `participants=[agentId]` row. The Captain's intent here is to make a **group**, so the very next `addParticipant` turns this thread into `[agentId, X]` (a distinct group); the untouched 1:1 default remains the 1:1. If the Captain abandons after materializing, a stray single-crew thread remains — harmless (the same agent's 1:1). Not a blocker; do not add backend de-dup in this AD.

### B. Mount it in `ProfileChatTab` — one line, disjoint from existing gates

Add a single sibling line next to the existing header mount (chat column, `:834`):

```tsx
{activeThreadId && <GroupChatHeader threadId={activeThreadId} />}
{!activeThreadId && <EmptyChatAddPeople agentId={agentId} />}   // ← AD-932
```

This is **mutually exclusive** with `GroupChatHeader` (one shows iff `activeThreadId`, the other iff `!activeThreadId`) and **disjoint** from AD-929's Files rail: `showWorkspaceFiles = !!activeThreadId && isWorkspaceRoom(...)` is `false` whenever `!activeThreadId`, so the rail never co-renders with this button. No conflict with `WorkspaceFilesRail`, `MeetingView`, or the meeting gates (all `activeThreadId`-gated).

### C. Test the component in isolation — do **NOT** full-render `ProfileChatTab`

The existing `ProfileChatTab` tests (`ProfileChatTab.groupsend.test.tsx:2`, `ProfileChatTab.bf294b.test.tsx`) state outright: *"The full ProfileChatTab is too heavy to render (audio/screen deps)"* and instead test a **faithful mirror** of the branch. AD-932 follows that precedent: `EmptyChatAddPeople` is a small standalone component (renderable like `AddParticipantPopover`/`GroupChatHeader`), so its create+wire logic and the `isCrew` self-gate are fully testable **without** mounting `ProfileChatTab`. The one-line `{!activeThreadId && …}` parent gate is visually trivial and is intentionally **not** covered by a heavy render test.

### D. Do not auto-open the picker (keep `GroupChatHeader` untouched)

Materialize → the header mounts with its visible add-participant button; the Captain clicks it to pick. Auto-opening the picker would require a new prop on `GroupChatHeader` (`defaultPickerOpen`); to keep this AD minimal and `GroupChatHeader`'s contract unchanged, **auto-open is deferred** (forward marker **AD-932a**). The visible "+ Add people" button already satisfies discoverability.

---

## Verified context (file:line — confirmed against HEAD)

**`ui/src/components/profile/ProfileChatTab.tsx`**
- `:483` `const activeThreadId = useStore((s) => threadId ?? s.threadIdByAgent.get(agentId));`
- `:496` `const showWorkspaceFiles = !!activeThreadId && isWorkspaceRoom(workspaceThread, agentsMap);` (AD-929 — `false` when `!activeThreadId`, so disjoint).
- `:834` `{activeThreadId && <GroupChatHeader threadId={activeThreadId} />}` (the mount point; add the sibling line here, inside the chat-column `<div>` opened near `:830`).
- `:36` `import { GroupChatHeader } from './GroupChatHeader';` (add `EmptyChatAddPeople` import alongside).

**`ui/src/components/profile/GroupChatHeader.tsx`**
- `:33` `if (!thread) return null;` — confirms the header cannot render thread-lessly (why materialization is required). **Unchanged by this AD.**
- `:25` `setPickerOpen` + `:225+` `add-participant-button` → `AddParticipantPopover` — the existing add flow that takes over after materialization.

**`ui/src/components/sidebar/threadApi.ts`**
- `:72` `createThread(body: CreateThreadBody): Promise<AD791aChatThreadView | null>` — `POST /api/threads`, returns `to_dict()` direct, honest-degrades to `null`. `CreateThreadBody.title` required (server `min_length=1`); `participants: string[]`.

**`ui/src/store/useStore.ts`**
- `:474` `setChatThread(thread)` → writes `chatThreads` Map (what `GroupChatHeader` reads).
- `:473/1273` `setThreadForAgent(agentId, threadId)` → writes `threadIdByAgent` (what `activeThreadId` reads).
- `Agent.isCrew` / `Agent.callsign` exist (used throughout `GroupChatHeader`/`AddParticipantPopover`).

**Backend (no change)** — `src/probos/threads/__init__.py:636` `get_or_create_default_for_agent` (`participants=[agent_id]`, `project_id=NULL`) is the server-side 1:1 default; `routers/threads.py:200` `POST /api/threads` accepts `CreateThreadRequest{title(min1,max200), participants, …}`.

**HXI glyphs** — reuse `UserPlus` from `../icons/Glyphs` (already imported by `GroupChatHeader`/`GroupChatListPanel`) + local inline SVG if needed. **Do NOT add exports to `Glyphs.tsx`.**

**No existing AD-932 files** (`file_search` `*ad932*`/`*ad-932*` → none; no `EmptyChatAddPeople.*`).

---

## Implementation

### Section 1 — `ui/src/components/profile/EmptyChatAddPeople.tsx` (new component)
Per Decision A: self-gates on `agent?.isCrew`; `handleAddPeople` → `createThread({ title: callsign, participants: [agentId] })` → `setChatThread(t)` + `setThreadForAgent(agentId, t.id)`; honest-degrade on `null`. Amber palette, inline-SVG `UserPlus`, **no emoji**. `data-testid="empty-chat-add-people"`.

### Section 2 — `ui/src/components/profile/ProfileChatTab.tsx` (one-line mount)
Add `import { EmptyChatAddPeople } from './EmptyChatAddPeople';` (by `:36`) and the sibling line `{!activeThreadId && <EmptyChatAddPeople agentId={agentId} />}` immediately after `:834`. **No other change** to `ProfileChatTab`.

---

## Tests (NO pytest — frontend-only)

### `ui/src/components/profile/__tests__/EmptyChatAddPeople.test.tsx` (≈8)
Mock `threadApi` (`vi.mock('../../sidebar/threadApi', () => ({ createThread: vi.fn() }))`); seed the **real** store (BF-287 style: `useStore.setState({ agents })`).
1. renders `empty-chat-add-people` for a crew agent.
2. returns `null` for a **non-crew** agent.
3. returns `null` for an **unknown** agentId (no agent in store).
4. click → `createThread` called once with `{ title: callsign, participants: [agentId] }`.
5. on success → `setChatThread(t)` written (`chatThreads.get(t.id)` present) **and** `setThreadForAgent` written (`threadIdByAgent.get(agentId) === t.id`).
6. **honest-degrade**: `createThread` resolves `null` → no store write (`threadIdByAgent` empty), button still present.
7. button is not disabled / clickable.
8. no emoji (`container.innerHTML` ∌ `\p{Extended_Pictographic}`).

**Gate (run both):**
```
cd ui ; npx vitest run
cd ui ; npm run build
```

---

## What this does NOT change (Do NOT build)

- **NO `GroupChatHeader` contract change.** Its `if (!thread) return null` and prop surface stay exactly as-is. No `defaultPickerOpen` prop (that is forward-marker AD-932a).
- **NO full-`ProfileChatTab` render test** (follow the `groupsend`/`bf294b` precedent — mirror/component tests only).
- **NO Ward Room DM convergence**, chain-pipeline, `ward_room/*`, or AD-574c-i changes.
- **NO backend changes**, no new endpoint, no `get_or_create_default_for_agent` exposure.
- **NO AD-929 Files-rail / AD-925 task-room changes.** The new mount is `!activeThreadId`-gated, disjoint from the rail.
- **NO AD-931 dependency.** Do not import from `chats/`; this AD only touches `profile/`.
- **NO `Glyphs.tsx` exports**, **NO `LeftRail.tsx` wire**.
- **NO eager thread creation on profile open** — the thread is materialized only on the explicit "+ Add people" click.

---

## Tracking

Update in the **same commit**: `PROGRESS.md` (AD-932 entry), `DECISIONS.md` (AD-932: discoverable add-people on an empty 1:1 — materialize-then-hand-off to `GroupChatHeader`). Note AD-932a (auto-open picker) as a forward marker.

---

## Acceptance criteria

- [ ] `ui/src/components/profile/EmptyChatAddPeople.tsx` created; self-gates on `isCrew`; materializes via `createThread([agentId])` then `setChatThread` + `setThreadForAgent`.
- [ ] `ProfileChatTab.tsx` mounts it via the single `{!activeThreadId && <EmptyChatAddPeople agentId={agentId} />}` line; no other `ProfileChatTab` change.
- [ ] `GroupChatHeader.tsx` **unchanged**.
- [ ] `cd ui ; npx vitest run` green with **≥8 new assertions** in `EmptyChatAddPeople.test.tsx`; `cd ui ; npm run build` clean.
- [ ] No emoji (HXI #3); amber palette; inline-SVG `UserPlus`.
- [ ] **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-08)

```
grep -n "activeThreadId =\|<GroupChatHeader\|showWorkspaceFiles =" ui/src/components/profile/ProfileChatTab.tsx
  483: const activeThreadId = useStore((s) => threadId ?? s.threadIdByAgent.get(agentId));
  496: const showWorkspaceFiles = !!activeThreadId && isWorkspaceRoom(workspaceThread, agentsMap);
  834: {activeThreadId && <GroupChatHeader threadId={activeThreadId} />}

grep -n "if (!thread) return null" ui/src/components/profile/GroupChatHeader.tsx
  33: if (!thread) return null;        // header cannot render thread-lessly → materialization required

grep -n "createThread\|setChatThread\|setThreadForAgent" ui/src/components/sidebar/threadApi.ts ui/src/store/useStore.ts
  threadApi.ts:72   createThread(body): Promise<AD791aChatThreadView | null>   // POST /api/threads, null on !ok
  useStore.ts:474   setChatThread(thread)        // writes chatThreads
  useStore.ts:1273  setThreadForAgent(agentId, threadId)   // writes threadIdByAgent

grep -n "too heavy to render" ui/src/components/profile/__tests__/ProfileChatTab.groupsend.test.tsx
  2: // The full ProfileChatTab is too heavy to render (audio/screen deps) — test a faithful mirror.
```
