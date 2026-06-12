# AD-919 — Group-Chat Visibility Surface + Join (final Phase-1 AD)

**One-line:** Give the Captain a focused "Group Chats" panel that lists every group chat — including the ones agents started on their own (AD-918 `metadata.created_by_agent`) — badges the agent-created ones, shows participant avatars, lets the Captain **Join** (AD-913 `add_participant`), and **opens** the existing AD-917 chat on click.

| | |
|---|---|
| **Status** | Ready to build |
| **Target repo** | OSS (`d:\ProbOS`) |
| **Highest committed AD** | **AD-918 (`bb9dfdc9`)**, on AD-917 `dae090a5` — NOT pushed |
| **Dependencies** | AD-913 (participants), AD-917 (UI chat host + `threadApi` wrappers + `AgentAvatarBadge`), AD-918 (`metadata.created_by_agent`) |
| **Estimated tests** | **Vitest only, +8 floor / +10 target** in one new file. **No pytest** (see Decision A — no backend change). |
| **Surface** | Frontend-only (UI) |

---

## Decision A — focused "Group Chats" panel, NOT the full LeftRail wire

The roadmap frames AD-919 as "wire the dormant LeftRail (AD-719b) into a live group-chat list." **Do NOT do that.** Verified reasons:

1. **The LeftRail has no group-chat concept.** [LeftRail.tsx](../ui/src/components/leftrail/LeftRail.tsx#L25-L34) exposes `LeftRailThread = { thread_id; title; is_dm? }` and `LeftRailProps = { agents; recentThreads; onSelectAgent?; onSelectThread? }`. There is no `participants`, no `metadata`, no `created_by_agent`, no Join. Delivering AD-919 through it would force extending its props/types/render — destroying its "self-contained presentational shell" contract and breaking its 5 vitest tests + the `CrewRoster.bridge` test.
2. **Wiring LeftRail into `App.tsx` is a layout reflow, not an additive edit.** It is explicitly deferred as forward marker **AD-719b-parent-wire** (import into `App.tsx` + reserve a root-layout slot + wire two zustand selectors), with default-flip deferred to **AD-719b-2** ([DECISIONS.md](../DECISIONS.md#L4019), [#L4029]). `App.tsx` is the root flex with `CognitiveCanvas`, `GlassLayer`, `TopNav`, and ~14 panels — inserting a persistent left column is high blast radius for the last Phase-1 AD.

**Chosen path:** a new self-contained `GroupChatListPanel`, surfaced by a `TopNav` toggle exactly like every other panel (NotebooksPanel precedent). This delivers the full Captain value (see agent-created chats → join → open) with the smallest, most additive `App.tsx`/store edits and a fully isolated unit test.

> **The full LeftRail wire (AD-719b-parent-wire) remains its own future AD.** AD-919 does **NOT** import, modify, or half-wire `LeftRail.tsx`.

---

## Decision B — no backend change

`GET /api/threads` already returns everything the panel needs. [list_threads](../src/probos/routers/threads.py#L82-L95) returns `{"threads": [t.to_dict()]}`, and [ChatThread.to_dict()](../src/probos/threads/__init__.py#L111-L127) includes `title`, `participants`, **`metadata`** (so `metadata.created_by_agent` from AD-918 is visible), and `task_id`. The client store type already carries it: [AD791aChatThreadView](../ui/src/store/useStore.ts#L209-L224) has `metadata?: Record<string, unknown>`.

**No backend gap → no `routers/threads.py` change, no new filter endpoint, no pytest.** The group-vs-1:1 split is a pure client-side predicate (Decision C).

---

## Decision C — what counts as a "group chat", and the Captain sentinel

**Group-chat predicate (client-side):** a thread is a group chat when
- `thread.metadata?.created_by_agent` is truthy (agent-initiated, AD-918), **OR**
- it has **≥2 crew participants**, where a crew participant is a `participants[]` id that (a) is not the literal `"captain"` and (b) resolves in `useStore(s => s.agents)` with `isCrew === true`.

A 1:1 default thread (one crew participant) is **excluded** from the list.

**Captain participant = the literal `"captain"` sentinel.** Verified consistent across the stack: AD-914 fan-out counts crew via `is_crew_agent(...)` which "naturally excludes the literal `\"captain\"` sentinel" ([DECISIONS.md](../DECISIONS.md#L55)); Captain posts use `author_id="captain"` (era-4/5 BF-055); and AD-917's `GroupChatHeader` already strips `"captain"` from its crew list. **Join therefore calls `addParticipant(threadId, "captain")`.** Adding `"captain"` does not change the crew count (it is excluded), so it never spuriously trips the AD-914 ≥2-crew gate.

> **Architectural note (non-blocking):** `"captain"` is the v1 sentinel. era-5 records that "if a future AD introduces a canonical captain DID / `is_captain()` helper, this check should switch to identity-based." Until then the literal string is correct and matches all current code. The Builder must use a single named constant `CAPTAIN_PARTICIPANT_ID = "captain"` in the panel with a comment citing this, so a future identity migration is a one-line change.

---

## Decision D — how "open a group chat on click" actually works

This is the single most important wiring detail and it is **not** what a naive reading suggests. The store has a top-level `activeThreadId` / `setActiveThread`, **but `ProfileChatTab` does not consume them.** Verified:

- [ProfileChatTab.tsx:475](../ui/src/components/profile/ProfileChatTab.tsx#L475): `const activeThreadId = useStore((s) => threadId ?? s.threadIdByAgent.get(agentId));` — the chat's thread is resolved **per agent** from `threadIdByAgent`, not from the store's top-level `activeThreadId`.
- [AgentProfilePanel.tsx:437](../ui/src/components/profile/AgentProfilePanel.tsx#L437): `{effectiveTab === 'chat' && isCrew && <ProfileChatTab agentId={agentId} />}` — the chat tab is hosted inside **one crew agent's** profile panel, mounted **without** a `threadId` prop.

So a group chat is always hosted in one crew "host" agent's chat tab (this is exactly how AD-917 group chats already live — an upgraded 1:1 still rendered in the original agent's panel via `threadIdByAgent`). **Open-on-click must:**

1. pick a **host** = first `participants[]` id that is not `"captain"` and resolves as a crew agent in `useStore(s => s.agents)`;
2. `setThreadForAgent(host, thread.id)` ([useStore.ts:467](../ui/src/store/useStore.ts#L467), impl [:1244](../ui/src/store/useStore.ts#L1244)) so the host's chat tab resolves the group thread;
3. `openAgentProfile(host)` ([useStore.ts:459](../ui/src/store/useStore.ts#L459), impl [:939](../ui/src/store/useStore.ts#L939)) to surface the panel.

If no crew host resolves (agents not yet hydrated), the row still renders but the open action is a no-op (Tier-2 honest-degrade). Group chats are crew-only (AD-918 creator auto-add; AD-914 needs ≥2 crew), so a real group chat always has a crew host.

> **Do NOT** wire the row open to `setChatThread`/`setActiveThread` — `ProfileChatTab` ignores those for thread selection, so it would be a silent no-op.

---

## Decision E — glyphs (keep Glyphs.tsx untouched)

- **Join button:** reuse the shared `UserPlus` glyph ([Glyphs.tsx:77](../ui/src/components/icons/Glyphs.tsx#L77)) — person+plus reads as "join."
- **Panel/section header "group" icon:** use a **local inline stroke-SVG** inside the panel (the `LeftRail` precedent — `GlyphAgents`/`GlyphThreads` are local inline functions, [LeftRail.tsx:90-118](../ui/src/components/leftrail/LeftRail.tsx#L90), not shared exports). HXI-compliant: `stroke` set, `strokeWidth={1.5}`, `strokeLinecap="round"`, no fills, no emoji.

> Deliberate scope-minimization: AD-919 does **NOT** add to `Glyphs.tsx`, so it does **NOT** touch `Glyphs.test.tsx` (whose `expect(count).toBe(30)` assertion would otherwise need a bump). One fewer file, one fewer gotcha.

---

## File set

| File | Change |
|---|---|
| `ui/src/components/groupchat/GroupChatListPanel.tsx` | **NEW** — the panel (default export, self-gates on `groupChatListOpen`). |
| `ui/src/components/groupchat/__tests__/GroupChatListPanel.test.tsx` | **NEW** — +8 floor / +10 target vitest. |
| `ui/src/store/useStore.ts` | **EDIT** — add `groupChatListOpen` state + 2 sync actions (mirror notebooks). |
| `ui/src/App.tsx` | **EDIT** — import panel, add `TopNav` `NavButton`, mount panel. |
| `PROGRESS.md` / `docs/development/roadmap.md` / `DECISIONS.md` | **EDIT** — tracking. |

**Reuse (do not re-author):** `listThreads()` + `addParticipant()` from [components/sidebar/threadApi.ts](../ui/src/components/sidebar/threadApi.ts#L31) ([addParticipant:131](../ui/src/components/sidebar/threadApi.ts#L131)); [AgentAvatarBadge](../ui/src/components/AgentAvatarBadge.tsx#L18) `{ agentId, callsign, department?, size? }`; `useStore(s => s.agents)`, `setThreadForAgent`, `openAgentProfile`; `UserPlus` glyph.

---

## Implementation

### Section 1 — store flag + actions (`ui/src/store/useStore.ts`)

Mirror the NotebooksPanel pattern exactly (synchronous open/close; the panel fetches on mount, so the actions stay trivial).

**1a. State shape** — near [`notebooksOpen: boolean;` (line ~380)](../ui/src/store/useStore.ts#L380) add:
```ts
  groupChatListOpen: boolean;
```

**1b. Action type decls** — near [`closeNotebooks: () => void;` (lines ~483-484)](../ui/src/store/useStore.ts#L483) add:
```ts
  openGroupChatList: () => void;
  closeGroupChatList: () => void;
```

**1c. Initial state** — near [`notebooksOpen: false,` (line ~832)](../ui/src/store/useStore.ts#L832) add:
```ts
  groupChatListOpen: false,
```

**1d. Action impls** — near [`closeNotebooks: () => set({...})` (line ~1004)](../ui/src/store/useStore.ts#L1004) add:
```ts
  openGroupChatList: () => set({ groupChatListOpen: true }),
  closeGroupChatList: () => set({ groupChatListOpen: false }),
```

### Section 2 — the panel (`ui/src/components/groupchat/GroupChatListPanel.tsx`)

Default-export React component, self-gating on `groupChatListOpen` (return `null` when closed — NotebooksPanel precedent [NotebooksPanel.tsx:26-27](../ui/src/components/NotebooksPanel.tsx#L26)).

**Constant:** `const CAPTAIN_PARTICIPANT_ID = 'captain';` with a comment citing Decision C.

**Data:**
- `const open = useStore(s => s.groupChatListOpen);` / `const close = useStore(s => s.closeGroupChatList);`
- `const agents = useStore(s => s.agents);`
- `const setThreadForAgent = useStore(s => s.setThreadForAgent);`
- `const openAgentProfile = useStore(s => s.openAgentProfile);`
- local `const [threads, setThreads] = useState<AD791aChatThreadView[]>([]);`
- `useEffect`: when `open` becomes true, `listThreads({ includeArchived: false }).then(setThreads)` (Tier-2: the wrapper already degrades to `[]`).

**Pure helpers (module-scope, exported for the test):**
- `crewParticipantIds(thread, agents): string[]` → `thread.participants.filter(p => p !== CAPTAIN_PARTICIPANT_ID && agents.get(p)?.isCrew)`.
- `isGroupChat(thread, agents): boolean` → `!!thread.metadata?.created_by_agent || crewParticipantIds(thread, agents).length >= 2`.
- `isAgentCreated(thread): boolean` → `!!thread.metadata?.created_by_agent`.
- `captainJoined(thread): boolean` → `thread.participants.includes(CAPTAIN_PARTICIPANT_ID)`.
- `hostAgentId(thread, agents): string | null` → first `crewParticipantIds(...)` entry, else `null`.

**Derived list:** `threads.filter(t => isGroupChat(t, agents))`, then **sort agent-created-and-un-joined to the top** (HXI #9 alert-driven ordering: chats an agent started that the Captain hasn't joined surface first), stable secondary order by `last_active_at` desc.

**Row render (per group chat):** `data-testid={\`group-chat-row-${thread.id}\`}`, the whole row clickable → `handleOpen(thread)`:
- title (`thread.title`);
- if `isAgentCreated(thread)`: an amber badge `data-testid="group-chat-agent-badge"` reading e.g. `Started by {creatorCallsign}` (resolve `metadata.created_by_agent` → `agents.get(id)?.callsign`, fallback to the raw id);
- participant avatars: for each `crewParticipantIds(thread, agents)` id render `<AgentAvatarBadge agentId={id} callsign={agents.get(id)?.callsign ?? '?'} department={agents.get(id)?.department} size={24} />`;
- a **Join** control (stop row-click propagation): when `!captainJoined(thread)` render a button `data-testid={\`group-chat-join-${thread.id}\`}` with the `UserPlus` glyph + label "Join" → `handleJoin(thread)`; when `captainJoined(thread)` render a subtle "Joined" marker `data-testid={\`group-chat-joined-${thread.id}\`}` (the row still opens on click).

**Handlers:**
- `handleOpen(thread)`: `const host = hostAgentId(thread, agents); if (!host) return; setThreadForAgent(host, thread.id); openAgentProfile(host);`
- `handleJoin(thread)`: `const updated = await addParticipant(thread.id, CAPTAIN_PARTICIPANT_ID); if (updated) setThreads(prev => prev.map(t => t.id === updated.id ? updated : t)); handleOpen(updated ?? thread);` (join, refresh the row so it flips to "Joined" and re-sorts, then open the chat).

**Empty state:** when the filtered list is empty, a calm "No group chats yet." line (HXI calm-by-default).

**HXI compliance:** amber `#f0b060` active accents, dim `#666680` inactive, JetBrains Mono, inline stroke-SVG only, **no emoji**. A local inline "group" glyph for the header (Decision E).

### Section 3 — `App.tsx` wiring (additive, mirror NotebooksPanel)

**3a. Import** — near [`import NotebooksPanel ...` (line 22)](../ui/src/App.tsx#L22):
```tsx
import GroupChatListPanel from './components/groupchat/GroupChatListPanel';
```

**3b. `TopNav` selectors** — near [lines 112-113](../ui/src/App.tsx#L112):
```tsx
  const groupChatListOpen = useStore(s => s.groupChatListOpen);
  const openGroupChatList = useStore(s => s.openGroupChatList);
```

**3c. `NavButton`** — near the existing NOTEBOOKS button [line 148](../ui/src/App.tsx#L148):
```tsx
      <NavButton label="GROUP CHATS" active={groupChatListOpen} onOpen={openGroupChatList} testId="group-chats-toggle" />
```

**3d. Mount** — near [`<NotebooksPanel />` (line 228)](../ui/src/App.tsx#L228):
```tsx
      <GroupChatListPanel />
```

---

## Tests — `ui/src/components/groupchat/__tests__/GroupChatListPanel.test.tsx`

Run: `cd ui && npx vitest run`. **Floor 8, target 10.** Use a **real store** (`useStore.setState(...)` / `useStore.getState()`) seeded with real fixtures — **no MagicMock at the store boundary** (BF-287). Mock the thread API: `vi.mock('../../sidebar/threadApi', () => ({ listThreads: vi.fn(), addParticipant: vi.fn() }))`.

Fixture: seed `agents` with two crew (`mccoy`→`Bones`/science, `scotty`→`Scott`/engineering, both `isCrew:true`) and set `groupChatListOpen:true`. `listThreads` resolves to:
- `g1` — participants `['mccoy','scotty']` (2 crew), no `created_by_agent` → group, Captain-built.
- `g2` — participants `['mccoy','scotty','captain']`, `metadata.created_by_agent:'mccoy'` → agent-created group, **Captain already joined**.
- `g3` — participants `['mccoy']`, no `created_by_agent` → 1:1, **excluded**.
- `g4` — participants `['scotty','mccoy']`, `metadata.created_by_agent:'scotty'`, **no** `'captain'` → agent-created, **un-joined**.

| # | Test | Assert |
|---|---|---|
| 1 | renders only group chats | rows for `g1`,`g2`,`g4` present; **`g3` (1:1) absent** |
| 2 | agent-created chats badged | `group-chat-agent-badge` present on `g2` & `g4`, absent on `g1` |
| 3 | participant avatars render | `g1` row contains 2 `agent-avatar-badge` nodes (Bones, Scott) |
| 4 | Join calls POST participants | click `group-chat-join-g4` → `addParticipant` called once with `('g4','captain')` |
| 5 | Join flips row to joined | mock `addParticipant` → returns `g4` with `'captain'` added; after click, `group-chat-joined-g4` present, `group-chat-join-g4` gone |
| 6 | row click opens chat | click `group-chat-row-g1` → `useStore.getState().threadIdByAgent.get('mccoy') === 'g1'` **and** `getState().activeProfileAgent === 'mccoy'` |
| 7 | Join also opens chat | after Join on `g4`, `getState().activeProfileAgent` is the host (`scotty` or `mccoy`) and `threadIdByAgent.get(host) === 'g4'` |
| 8 | un-joined agent-created sorts first | DOM order: `g4` (agent-created, un-joined) appears before `g1`/`g2` |
| 9 | self-gates when closed | with `groupChatListOpen:false`, panel renders nothing |
| 10 | no-emoji guard | `container.innerHTML` has no `/\p{Extended_Pictographic}/u` match |

---

## What this does NOT change (hard boundaries)

- **No meeting / voice / VRM avatars** — that is Phase 2 (AD-920/921/922/923). **AD-919 is the LAST Phase-1 AD.**
- **No `LeftRail.tsx` change and no `App.tsx` layout reflow.** The full LeftRail parent-wire stays forward marker **AD-719b-parent-wire**; the default-flip stays **AD-719b-2**. Do not import or modify `LeftRail.tsx`.
- **No backend change** — `routers/threads.py`, `threads/__init__.py`, the store, no new endpoint/filter, no new EventType. (Decision B.)
- **No change to `ProfileChatTab.tsx`, `GroupChatHeader.tsx`, `AddParticipantPopover.tsx`** (AD-917), the AD-914 fan-out (`routers/thread_fanout.py`), or the AD-918 `agent_group_chat.py` service.
- **No `Glyphs.tsx` / `Glyphs.test.tsx` change** (Decision E — local inline header glyph + reuse `UserPlus`).
- **No consensus gate** — Join is a reversible Captain-authority participant add (AD-913 `remove_participant` reverses it); Safety-Budget / Minimal-Authority.

---

## Tracking

- `docs/development/roadmap.md`: flip the **AD-919** row to `SHIPPED <date> gate-verified` (do not touch the AD-719b/AD-719b-2 forward markers).
- `PROGRESS.md`: prepend an AD-919 block.
- `DECISIONS.md`: add an **AD-919** entry (above AD-918) recording (a) focused-panel-over-LeftRail rationale, (b) the `threadIdByAgent` + `openAgentProfile` host-routing for open-on-click, (c) the literal `"captain"` join sentinel, (d) frontend-only / no backend change.

---

## Acceptance criteria

1. `GroupChatListPanel` lists only group chats (`metadata.created_by_agent` **or** ≥2 crew participants); 1:1 default threads excluded.
2. Agent-created chats are visibly badged; un-joined agent-created chats sort to the top (HXI #9).
3. Each row shows participant avatars via `AgentAvatarBadge` sourced from `useStore(s => s.agents)`.
4. **Join** → `addParticipant(threadId, "captain")`; on success the row flips to "Joined" and the chat opens.
5. Clicking a row opens the group chat via `setThreadForAgent(host, threadId)` + `openAgentProfile(host)` (host = first crew participant).
6. Panel toggled from a `TopNav` `NavButton` (`group-chats-toggle`); self-gates on `groupChatListOpen`; no `App.tsx` layout reflow.
7. New vitest file green, **+8 floor / +10 target**; full UI suite green (`cd ui && npx vitest run`); `npm run build` (tsc -b + vite) green.
8. No emoji anywhere in the panel (guard test passes); inline stroke-SVG glyphs only; amber palette.
9. No backend change; no pytest required.
10. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-07)

```
# LeftRail is built but NOT imported by App.tsx; has no group/metadata/join concept
ui/src/components/leftrail/LeftRail.tsx:25   LeftRailThread = { thread_id; title; is_dm? }   (no participants/metadata/join)
DECISIONS.md:4019                            "LeftRail is built but NOT yet imported by App.tsx"
DECISIONS.md:4029                            forward markers AD-719b-parent-wire + AD-719b-2
grep "LeftRail" ui/src/**/*.tsx              only LeftRail.tsx + 2 test files reference it (App.tsx does NOT)

# GET /api/threads already returns metadata.created_by_agent — no backend gap
src/probos/routers/threads.py:82-95          list_threads -> {"threads": [t.to_dict()]}
src/probos/threads/__init__.py:111-127       to_dict() includes "title","participants","metadata","task_id"
src/probos/threads/__init__.py:193,234       create_thread(metadata=...) writes the AD-918 col
ui/src/store/useStore.ts:209-224             AD791aChatThreadView.metadata?: Record<string, unknown>

# Join + participants
src/probos/routers/threads.py:302-316        POST /{id}/participants -> thread.to_dict()
ui/src/components/sidebar/threadApi.ts:131-148  addParticipant(threadId, agentId) -> AD791aChatThreadView|null
ui/src/components/sidebar/threadApi.ts:31-44    listThreads(opts) -> AD791aChatThreadView[]
DECISIONS.md:55                              AD-914 crew gate "naturally excludes the literal 'captain' sentinel"

# Open-on-click is threadIdByAgent + openAgentProfile (NOT store.activeThreadId)
ui/src/components/profile/ProfileChatTab.tsx:475   activeThreadId = threadId ?? s.threadIdByAgent.get(agentId)
ui/src/components/profile/AgentProfilePanel.tsx:437 chat tab mounts <ProfileChatTab agentId={agentId}/> when isCrew
ui/src/store/useStore.ts:467,1244            setThreadForAgent(agentId, threadId)
ui/src/store/useStore.ts:459,939             openAgentProfile(agentId) -> set activeProfileAgent
ui/src/store/useStore.ts:335                 threadIdByAgent: Map<string,string>

# Reuse primitives
ui/src/components/AgentAvatarBadge.tsx:18-26  props { agentId, callsign, department?, size? }
ui/src/components/icons/Glyphs.tsx:77         UserPlus (reuse for Join)
ui/src/components/icons/Glyphs.test.tsx:~50   expect(count).toBe(30)  (NOT touched — local inline header glyph)
ui/src/store/useStore.ts:266                  agents: Map<string, Agent>  (callsign/department/isCrew on hydrate ~1760-1767)

# Panel precedent (NotebooksPanel): open flag self-gate + NavButton + unconditional mount
ui/src/components/NotebooksPanel.tsx:26-27    open = s.notebooksOpen; close = s.closeNotebooks  (returns null when closed)
ui/src/App.tsx:22 / :112-113 / :148 / :228     import / selectors / NavButton / mount
ui/src/store/useStore.ts:380 / :483-484 / :832 / :966,1004  notebooksOpen state + open/close actions
```
