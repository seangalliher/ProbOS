# AD-931: Unified CHATS surface — one Teams/Slack-style home for 1:1 + group chats, with "+ New chat"

**Status:** Ready to build (frontend-only)
**Dependencies:** AD-917 (group chat UI + `AddParticipantPopover`), AD-918 (`metadata.created_by_agent`), AD-919 (the Group Chats panel this AD repurposes), AD-791a (`createThread`/`listThreads`/the per-agent default 1:1 thread)
**Estimated tests:** **+25 Vitest floor** across 3 new files (`chatFilters.test.ts` ~8, `ChatsPanel.test.tsx` ~11, `NewChatModal.test.tsx` ~6). This **supersedes** the 10 AD-919 tests (deleted), so the **net suite delta is ≈ +15**. **NO pytest** — every endpoint already exists.
**Highest committed AD:** **AD-930** (pushed). AD-931 / AD-932 are **unused**.
**Commit policy:** **COMMIT LOCAL ONLY. DO NOT PUSH.** The Captain decides when to push.

---

## One-line

Repurpose the AD-919 "GROUP CHATS" panel into **one unified "CHATS" panel** that lists **both 1:1 and group** conversations, with a prominent **"+ New chat"** picker — pick **1** agent → open that agent's 1:1; pick **2+** → `createThread` a group and open it. This single entry point closes the "no way to start a chat" gap and is the Teams/Slack chats home. **No backend, no Ward Room DM convergence.**

---

## Problem (Captain's observations — verified against HEAD)

1. **No way to start a new chat.** `GroupChatListPanel` (AD-919) is **visibility + Join only** — it lists existing group chats and lets the Captain Join, but there is **no create affordance** anywhere in the HXI.
2. **Two separate mental models.** The TopNav exposes "GROUP CHATS" as a thing apart from 1:1 DMs. In Teams/Slack there is **one Chats list** holding both. Today a 1:1 lives only inside an agent's profile chat tab and never appears in a list.
3. The unified entry point also addresses the "convert 1:1 → group" gap: from "+ New chat" the Captain picks 2+ agents to start a group directly. (The *in-chat* discoverable add on an empty 1:1 is the sibling **AD-932**, intentionally split out.)

---

## Decision (what this builds, and why)

### A. Repurpose, don't add a sibling — and rename the surface to "Chats"

AD-931 **moves and renames** the existing panel rather than adding a second one (a sibling would violate "one chats home"):

| Old (AD-919) | New (AD-931) |
|---|---|
| `ui/src/components/groupchat/GroupChatListPanel.tsx` | `ui/src/components/chats/ChatsPanel.tsx` |
| `ui/src/components/groupchat/__tests__/GroupChatListPanel.test.tsx` | `ui/src/components/chats/__tests__/ChatsPanel.test.tsx` |
| (pure helpers inline in the panel) | `ui/src/components/chats/chatFilters.ts` (moved + extended) |
| store flag `groupChatListOpen` / `openGroupChatList` / `closeGroupChatList` | `chatsOpen` / `openChats` / `closeChats` |
| TopNav `label="GROUP CHATS"` testId `group-chats-toggle` | `label="CHATS"` testId `chats-toggle` |

**Why rename the internal names too (not just the label):** once the panel lists 1:1s, the name `GroupChatListPanel` / `groupChatListOpen` is actively misleading to every future contributor. The rename is **mechanical and fully contained** — `grep` confirms the flag/panel are referenced **only** in `useStore.ts`, `App.tsx`, the panel, and its test (no App-level test, no other consumer; see *Verified context*). The in-place alternative (keep the old names, just relabel the button) was rejected: it leaves a load-bearing-misleading name behind.

> **`LeftRail.tsx` stays untouched** (still the forward-marker `AD-719b-parent-wire`). This AD does not wire the left rail.

### B. The unified filter: 1:1 + group, **excluding task rooms**

The new pure helper `isChat` widens the AD-919 `isGroupChat` gate to also admit 1:1s, while **excluding AD-925 task rooms** (which set `task_id`) so the Chats list reads like Teams' *Chat* list, not its *Teams/Channels* list:

```ts
// A "chat" = a 1:1 or group CONVERSATION, never a task workspace room.
export function isChat(thread: AD791aChatThreadView, agents: AgentMap): boolean {
  if (thread.task_id) return false;                                  // exclude AD-925 task rooms
  return isAgentCreated(thread) || crewParticipantIds(thread, agents).length >= 1;
}
```

- **1:1** — `participants=[agentId]`, 1 crew, no `task_id` → included (the per-agent default thread, `metadata.is_default=true`).
- **group** — ≥2 crew **or** `created_by_agent` → included (existing `isGroupChat`).
- **task room** — `task_id` set (≥2 crew) → **excluded**.
- **captain-only / empty / unknown-participant** — 0 crew, not agent-created → excluded.

Within a row, `isGroupChat` still distinguishes the two: a **group** row keeps the AD-919 treatment (multi-avatar strip, `created_by_agent` badge, **Join** when `!captainJoined`); a **1:1** row shows a single avatar + callsign and **no Join** (Join — `addParticipant('captain')` — is meaningless for a 1:1, which has no second crew slot). Both open via the same host pattern.

### C. "+ New chat" — branch on selection count (avoids duplicate-1:1 divergence)

The "+ New chat" button opens `NewChatModal`, a participant picker. On confirm:

- **1 agent selected → 1:1:** `openAgentProfile(agentId)` + `closeChats()`. **Do NOT `createThread`.** The 1:1 default thread is owned server-side by `get_or_create_default_for_agent` (created on first message via the existing `agent_chat` path). `createThread([agentId])` here would mint a **second** `participants=[agentId]` row that the `agent_chat` default lookup (`ORDER BY created_at ASC LIMIT 1`) may not pick → a divergent/duplicate 1:1. Opening the agent profile reuses the existing, correct mechanism.
- **2+ agents selected → group:** `createThread({ title, participants: selected })` → on success `setThreadForAgent(selected[0], thread.id)` + `openAgentProfile(selected[0])` + `closeChats()`. Host = first selected crew (verbatim AD-919 `handleOpen` pattern). `createThread` honest-degrades to `null` → keep the modal open (Tier-2), no throw.

`title` for the group defaults to the selected callsigns joined (`"Bones, Scott"`), falling back to `"New group chat"` (satisfies the server's `min_length=1`).

### D. Reuse `AddParticipantPopover` as the picker (DRY)

`NewChatModal` **reuses** the AD-917 `AddParticipantPopover` (crew filter, keyboard nav, dedupe-by-callsign, avatar rows) as its selection surface rather than rebuilding a multi-select:

- Pass the running selection as `existingParticipantIds={selected}` → already-picked agents drop out of the list automatically.
- `onAdd={(id) => setSelected(prev => [...prev, id])}` accumulates instead of POSTing.
- Render `selected` as removable chips/avatars above the popover; a **"Start chat"** CTA is **disabled until `selected.length >= 1`**.
- `onClose` closes the modal.

This is clean reuse — the popover is already a pure selector whose parent owns the action.

---

## Verified context (file:line — confirmed against HEAD)

**threadApi — `ui/src/components/sidebar/threadApi.ts` (UNCHANGED, reused)**
- `createThread(body: CreateThreadBody): Promise<AD791aChatThreadView | null>` — `POST /api/threads`, returns `thread.to_dict()` **direct**; honest-degrades to `null`. `CreateThreadBody = { title: string; participants: string[]; project_id?; task_id?; preprompt?; model? }`.
- `listThreads({ includeArchived, limit }): Promise<AD791aChatThreadView[]>` — `GET /api/threads?include_archived=&limit=`, returns `{threads:[…]}`; honest-degrades to `[]`.
- `addParticipant(threadId, agentId)` — `POST /api/threads/{id}/participants`.

**Backend (no change — proves 1:1s are listable)**
- `src/probos/routers/threads.py:165` `list_threads(...)` → `store.list_threads(include_archived, project_id, limit)` → `{"threads": [t.to_dict() …]}`. **No participant filter.**
- `src/probos/threads/__init__.py:244` `ChatThreadStore.list_threads` returns **all** non-archived rows, `ORDER BY pinned DESC, last_active_at DESC`.
- `src/probos/threads/__init__.py:636` `get_or_create_default_for_agent` inserts a `chat_threads` row: `participants=[agent_id]`, `title=callsign`, `project_id=NULL`, `task_id=NULL`, `metadata={"is_default": true}`. **⇒ a 1:1 IS a listed `chat_threads` row.** (Created on first message; a never-messaged 1:1 has no row yet — correct.)
- `src/probos/cognitive/crew_executor.py:319` AD-925 task room → `create_group_chat(..., task_id=parent_id, participants=crew[1:])` ⇒ task rooms carry `task_id` (the `isChat` exclusion key).

**Panel being repurposed — `ui/src/components/groupchat/GroupChatListPanel.tsx`**
- Exported pure helpers (move to `chatFilters.ts` verbatim): `crewParticipantIds`, `isAgentCreated`, `isGroupChat`, `captainJoined`, `hostAgentId`.
- `CAPTAIN_PARTICIPANT_ID='captain'`, `COLOR_ACTIVE='#f0b060'`, `COLOR_INACTIVE='#666680'`.
- Reads `groupChatListOpen`, `closeGroupChatList`, `agents`, `setThreadForAgent`, `openAgentProfile`. `useEffect` fetches `listThreads({includeArchived:false})` on open. `handleOpen` = `setThreadForAgent(host, thread.id) + openAgentProfile(host)` (host = `hostAgentId`). `handleJoin` = `addParticipant(thread.id, 'captain')`.
- Local `GlyphGroup` SVG; imports `{ UserPlus, Close }` from `../icons/Glyphs`.
- testIds: `group-chat-list-panel`, `group-chat-close`, `group-chat-empty`, `group-chat-row-{id}`, `group-chat-agent-badge`, `group-chat-join-{id}`, `group-chat-joined-{id}`.

**Picker to reuse — `ui/src/components/profile/AddParticipantPopover.tsx`**
- `AddParticipantPopover({ existingParticipantIds: string[]; onAdd: (agentId: string) => void; onClose: () => void })` — pure selector; filters crew, excludes `existingParticipantIds` + `'captain'`, dedupes by callsign, `slice(0,8)`; keyboard `ArrowUp/Down`, `Enter|Tab`→`onAdd`, `Esc`→`onClose`. testIds: `add-participant-popover`, `add-participant-filter`, `add-participant-row`.

**Store — `ui/src/store/useStore.ts`**
- `:210` `interface AD791aChatThreadView { id; title; participants: string[]; created_at; last_active_at; project_id?; task_id?; …; metadata?: Record<string,unknown> }`
- `:336` `threadIdByAgent: Map<string,string>`; `:393` `groupChatListOpen: boolean`; `:854` initial `false`.
- `:465/954` `openAgentProfile(agentId)` → `set({ activeProfileAgent: agentId, pinnedAgent: null })`.
- `:473/1273` `setThreadForAgent(agentId, threadId)`; `:474` `setChatThread`; `:499/500/1039/1040` `openGroupChatList`/`closeGroupChatList`.

**TopNav — `ui/src/App.tsx`**
- `:23` `import GroupChatListPanel from './components/groupchat/GroupChatListPanel';`
- `:116-117` `const groupChatListOpen = useStore(s => s.groupChatListOpen); const openGroupChatList = useStore(s => s.openGroupChatList);`
- `:150` `<NavButton label="GROUP CHATS" active={groupChatListOpen} onOpen={openGroupChatList} testId="group-chats-toggle" />`
- `:234` `<GroupChatListPanel />`

**Rename blast radius (grep `group-chats-toggle|groupChatListOpen|GroupChatListPanel|openGroupChatList`)** — **only** `useStore.ts`, `App.tsx`, the panel file, and `GroupChatListPanel.test.tsx`. **No App-level test references the flag/toggle.**

**AD-919 test contract — `ui/src/components/groupchat/__tests__/GroupChatListPanel.test.tsx` (10 tests, to be superseded)**
- `vi.mock('../../sidebar/threadApi', () => ({ listThreads: vi.fn(), addParticipant: vi.fn() }))`; seeds the **real** store (BF-287 fixture style).
- Fixtures: G1 (2 crew → group), G2 (agent-created, joined), **G3 (1 crew → 1:1, currently asserted EXCLUDED)**, G4 (agent-created, not joined).
- Test #1 `'renders only group chats (1:1 default thread excluded)'` asserts `queryByTestId('group-chat-row-g3')` is `null`. **This contract flips** (1:1 now INCLUDED).

**HXI glyph gotcha** — reuse the already-exported `UserPlus`/`Close` from `icons/Glyphs` + **local** inline SVGs (as `GroupChatListPanel`'s `GlyphGroup` does). **Do NOT add exports to `Glyphs.tsx`** (its export-count test must stay green).

**No existing AD-931 files** (`file_search` `*ad931*` / `*ad-931*` returns none; `ui/src/components/chats/` does not exist).

---

## Implementation

Create `ui/src/components/chats/` (filters, panel, modal, tests). Rename the store flag. Re-point `App.tsx`. Delete the old `groupchat/` panel + test. **No backend, no new endpoint, no new store slice beyond the flag rename.**

### Section 1 — `ui/src/components/chats/chatFilters.ts` (pure helpers)

Move the 5 exported helpers from `GroupChatListPanel.tsx` **verbatim** (`crewParticipantIds`, `isAgentCreated`, `isGroupChat`, `captainJoined`, `hostAgentId`), plus the `CAPTAIN_PARTICIPANT_ID` / color constants. Add the new `isChat` (Decision B). Keep `AgentMap = Map<string, Agent>`.

### Section 2 — `ui/src/components/chats/ChatsPanel.tsx` (the unified panel)

Port `GroupChatListPanel` with these changes:
- Import helpers from `./chatFilters`; read `chatsOpen` / `closeChats` (renamed).
- Filter `threads.filter(t => isChat(t, agents))` (was `isGroupChat`). Keep the HXI-#9 sort (un-joined agent-created → top, then `last_active_at` desc). 1:1s sort by recency among the rest.
- Header: glyph + label **`CHATS`** + a **"+ New chat"** button (`data-testid="new-chat-button"`, `UserPlus` glyph, amber) + close.
- Row rendering: if `isGroupChat(thread)` → existing group row (avatars, badge, Join when `!captainJoined`); else → 1:1 row (single avatar + callsign, no Join, no badge). Both `onClick={() => handleOpen(thread)}` (unchanged host pattern).
- `{newChatOpen && <NewChatModal onClose={() => setNewChatOpen(false)} />}` — modal owns create+open+`closeChats`.
- **Rename all testIds** `group-chat-*` → `chat-*`: `chats-panel`, `chats-close`, `chats-empty` (`"No chats yet."`), `chat-row-{id}`, `chat-agent-badge`, `chat-join-{id}`, `chat-joined-{id}`. Keep `agent-avatar-badge` (from `AgentAvatarBadge`).

### Section 3 — `ui/src/components/chats/NewChatModal.tsx` (the picker)

```ts
export function NewChatModal({ onClose }: { onClose: () => void }) { … }
```
- `const [selected, setSelected] = useState<string[]>([])`.
- Reads `agents`, `setThreadForAgent`, `openAgentProfile`, `closeChats` from the store.
- Renders selected as removable chips (`data-testid="new-chat-selected-{id}"`), then `<AddParticipantPopover existingParticipantIds={selected} onAdd={(id) => setSelected(p => [...p, id])} onClose={onClose} />`.
- **"Start chat"** button `data-testid="new-chat-start"`, **disabled when `selected.length < 1`**. **Cancel** `data-testid="new-chat-cancel"` → `onClose`.
- `onStart`:
  - `selected.length === 1` → `openAgentProfile(selected[0]); closeChats(); onClose();` (NO `createThread`).
  - `selected.length >= 2` → `const title = callsigns.join(', ') || 'New group chat'; const t = await createThread({ title, participants: selected }); if (!t) return; setThreadForAgent(selected[0], t.id); openAgentProfile(selected[0]); closeChats(); onClose();`
- `data-testid="new-chat-modal"`. Inline SVG / amber palette, **no emoji**.

### Section 4 — store rename (`ui/src/store/useStore.ts`)

Rename the 1 flag + 2 actions (4 sites): `groupChatListOpen→chatsOpen`, `openGroupChatList→openChats`, `closeGroupChatList→closeChats` (interface decls, initial-state `false`, and the two `set(...)` action bodies). No behavior change.

### Section 5 — `ui/src/App.tsx` re-point (3 edits)

- `:23` import `ChatsPanel from './components/chats/ChatsPanel'`.
- `:116-117` `chatsOpen` / `openChats` hooks.
- `:150` `<NavButton label="CHATS" active={chatsOpen} onOpen={openChats} testId="chats-toggle" />`.
- `:234` `<ChatsPanel />`.

### Section 6 — delete superseded files

Delete `ui/src/components/groupchat/GroupChatListPanel.tsx` and `…/__tests__/GroupChatListPanel.test.tsx` (and the now-empty `groupchat/` dirs if nothing else lives there — `file_search` `ui/src/components/groupchat/**` first; if other files exist, leave them).

---

## Tests (NO pytest — frontend-only)

### `ui/src/components/chats/__tests__/chatFilters.test.ts` (≈8)
`isChat`: (1) 1:1 (1 crew, no task_id) → true; (2) ≥2 crew → true; (3) agent-created → true; (4) **task room (`task_id` set + 2 crew) → false**; (5) captain-only / 0-crew non-agent-created → false. `isGroupChat`: (6) ≥2 crew true, 1 crew false. `hostAgentId`: (7) first crew. `captainJoined`: (8) sentinel present/absent.

### `ui/src/components/chats/__tests__/ChatsPanel.test.tsx` (≈11 — migrate the 10 AD-919 tests, flip #1)
Mock `threadApi` (`listThreads`, `addParticipant`), seed the real store (BF-287 style). Reuse the G1–G4 fixtures **plus a task-room fixture `T1` (`task_id:'task-1'`, 2 crew)**:
1. **lists BOTH 1:1 and group; excludes task room** — `chat-row-g1/g2/g3/g4` present, **`chat-row-g3` (1:1) PRESENT**, `chat-row-t1` **absent**.
2. badges agent-created only (`chat-agent-badge` on g2/g4, not g1/g3).
3. group row renders an avatar per crew member.
4. **1:1 row shows no Join control** (`chat-join-g3` absent).
5. Join calls `addParticipant('g4','captain')` once.
6. Join flips `chat-join-g4` → `chat-joined-g4`.
7. clicking a group row opens host: `threadIdByAgent.get('mccoy')==='g1'` & `activeProfileAgent==='mccoy'`.
8. clicking a 1:1 row opens host: `activeProfileAgent==='mccoy'` (g3 host).
9. sorts un-joined agent-created (g4) above g1/g2 (HXI #9).
10. self-gates: renders nothing when `chatsOpen:false`.
11. no emoji (`container.innerHTML` ∌ `\p{Extended_Pictographic}`).

### `ui/src/components/chats/__tests__/NewChatModal.test.tsx` (≈6)
1. `new-chat-button` opens `new-chat-modal`; popover (`add-participant-popover`) renders.
2. **`new-chat-start` disabled with 0 selected**, enabled after 1 pick.
3. **1 selected → `openAgentProfile(id)` called, `createThread` NOT called**, panel closed (`chatsOpen:false`).
4. **2 selected → `createThread({participants:[a,b], title})` called, then `setThreadForAgent(a, newId)` + `openAgentProfile(a)`**.
5. picked agent removable via `new-chat-selected-{id}` chip (drops back into the popover list).
6. no emoji.

**Gate (run both):**
```
cd ui ; npx vitest run
cd ui ; npm run build
```

---

## What this does NOT change (Do NOT build)

- **NO Ward Room DM convergence.** Do not touch Ward Room DMs (`channel_type=='dm'`, `DmActivityLog`), the **chain pipeline**, `ward_room/*`, `ward_room_router.py`, or **AD-574c-i**. The two DM systems are a deliberate A/B test (pipeline decision pending).
- **NO backend changes.** `routers/threads.py`, `threads/__init__.py`, and every endpoint are reused as-is.
- **NO `LeftRail.tsx` wire.** It stays the forward marker.
- **NO `Glyphs.tsx` exports.** Reuse `UserPlus`/`Close` + local inline SVGs.
- **NO new store slice** beyond renaming the one panel flag.
- **NO `createThread` for the 1-agent (1:1) path** (Decision C — avoids duplicate/divergent 1:1 threads).
- **NO AD-925/926/927/929 task-room or Files-rail changes.** The `isChat` `!task_id` filter merely *excludes* task rooms from the list.
- **AD-932 (discoverable in-chat add on an empty 1:1) is a separate AD** — do not fold it in here.

---

## Tracking

Update in the **same commit**: `PROGRESS.md` (AD-931 entry), `DECISIONS.md` (AD-931: unified CHATS surface — repurpose AD-919 panel, `isChat` filter, branch new-chat on selection count), `docs/development/roadmap.md` if a Group-Chat-epic line exists.

---

## Acceptance criteria

- [ ] `ui/src/components/chats/{chatFilters.ts, ChatsPanel.tsx, NewChatModal.tsx}` created; `groupchat/GroupChatListPanel.tsx` + its test deleted.
- [ ] Store flag renamed `chatsOpen`/`openChats`/`closeChats`; `App.tsx` shows **CHATS** (`chats-toggle`) and mounts `<ChatsPanel />`.
- [ ] CHATS panel lists 1:1 **and** group chats; task rooms (`task_id`) excluded; 1:1 rows have no Join.
- [ ] "+ New chat": 1 agent → `openAgentProfile` (no `createThread`); 2+ → `createThread` + open host; Start disabled with 0 selected.
- [ ] `cd ui ; npx vitest run` green with **≥25 new assertions** across the 3 new files; `cd ui ; npm run build` clean.
- [ ] No emoji in any new component (HXI #3); amber/dim palette; inline-SVG glyphs only.
- [ ] **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-08)

```
grep -n "createThread\|listThreads\|addParticipant" ui/src/components/sidebar/threadApi.ts
  64: export interface CreateThreadBody { title: string; participants: string[]; project_id?…; task_id?…; preprompt?…; model?… }
  72: export async function createThread(body: CreateThreadBody): Promise<AD791aChatThreadView | null>
  31: export async function listThreads(opts): Promise<AD791aChatThreadView[]>   // GET /api/threads -> {threads:[…]}
 162: export async function addParticipant(threadId, agentId): Promise<AD791aChatThreadView | null>

grep -n "def list_threads\|def get_or_create_default_for_agent\|task_id=parent_id" src/probos/**/*.py
  threads/__init__.py:244  def list_threads(... include_archived, project_id, task_id, limit)   # no participant filter
  threads/__init__.py:636  def get_or_create_default_for_agent(...)  -> participants=[agent_id], metadata={"is_default":true}, task_id=NULL
  routers/threads.py:165   list_threads(...) -> {"threads": [t.to_dict() …]}
  crew_executor.py:319     create_group_chat(... task_id=parent_id, participants=crew[1:])   # task room carries task_id

grep -n "AddParticipantPopover(" ui/src/components/profile/AddParticipantPopover.tsx
  27: export function AddParticipantPopover({ existingParticipantIds, onAdd, onClose })   // single-select onAdd

grep -rn "group-chats-toggle\|groupChatListOpen\|GroupChatListPanel\|openGroupChatList" ui/src
  useStore.ts (393/854/499/500/1039/1040)  App.tsx (23/116/117/150/234)  GroupChatListPanel.tsx  GroupChatListPanel.test.tsx
  # contained blast radius — NO App-level test references the flag/toggle

grep -n "export function isGroupChat\|export function crewParticipantIds\|export function hostAgentId" ui/src/components/groupchat/GroupChatListPanel.tsx
  43/50/55/60/65: crewParticipantIds / isAgentCreated / isGroupChat / captainJoined / hostAgentId  (move to chatFilters.ts)
```
