# AD-929: Unified Workspace View — the Teams-channel surface for a task room

**Status:** Ready to build (frontend-only)
**Dependencies:** AD-917 (group chat UI), AD-920 (meeting view), AD-925 (auto task room), AD-926 (Inputs pane), AD-927/AD-797 (Outputs/artifacts)
**Estimated tests:** +14 Vitest floor (target +16). NO pytest (frontend-only; all endpoints already exist).
**Highest committed AD:** **AD-927** (`52f34cd7`, HEAD, **4 ahead of origin — LOCAL ONLY, NOT pushed**). origin/main = AD-924.
**Commit policy:** **COMMIT LOCAL ONLY. DO NOT PUSH.** The entire Task Workspace Rooms epic (AD-925..929) is being held for Captain review.

---

## One-line

Assemble the AD-917 conversation + the AD-926 Inputs pane + the AD-927/AD-797 artifact Outputs into ONE collapsible **"Files" rail** beside the chat, gated to workspace rooms, so a task room reads like a Microsoft Teams channel (Conversation + Files) instead of a bare chat.

---

## Problem

The Task Workspace Rooms epic delivered the substrate (AD-925 auto task room) and both file folders (AD-926 Inputs, AD-927 Outputs), but the pieces are **not assembled into one surface**:

- `InputsList` (AD-926) is a self-contained presentational list that is **mounted nowhere** — `grep` finds it only in its own test.
- The artifact Outputs (`ArtifactDrawer`, AD-797) is mounted **only in `CompactApp`** (the Yeo tray), as the third column `[ThreadSidebar | ProfileChatTab | ArtifactDrawer]`. It is **absent from the full HXI**, where task/group rooms actually open (AD-919 routes a room to `openAgentProfile(host)` → `AgentProfilePanel` → `ProfileChatTab`).
- A Captain opening a task room sees a transcript and nothing else — no shared inputs, no produced artifacts beside the conversation.

The Captain's refined goal: *"an experience similar to what HR would see collaborating in Microsoft Teams."* Teams maps a project channel to: **Conversation** (the transcript) + **Files** (shared inputs + produced outputs) + **Meet** (already built: AD-920 `MeetingView`). AD-929 is the surface that binds Conversation + Files into one workspace view bound to the room's `thread_id`.

---

## Decision (what this prompt builds, and why)

### Layout = a collapsible right-hand **"Files" rail inside `ProfileChatTab`** (chosen over a tab bar)

`ProfileChatTab` is the **only mount common to both hosts** — `CompactApp` (Yeo tray) *and* `AgentProfilePanel` (full HXI). Putting the workspace Files surface inside `ProfileChatTab` means it travels with the conversation into both hosts with one component, no host-specific layout surgery.

The rail keeps the **conversation as the primary column** (Teams defaults a channel to its Conversation) and adds a right rail with two stacked sections — **INPUTS** (top) + **OUTPUTS** (bottom) — matching Teams' "Conversation + Files." It reuses the existing HXI right-rail idiom already established by `ArtifactDrawer`.

**A tab bar atop the room was rejected:**
- It hides the conversation when viewing Files; a live collaboration room wants Files co-visible with the transcript.
- `AgentProfilePanel` already has a **per-agent** tab bar (`Chat | Work | Memory | Profile | Health | Self-image`). A **per-thread** "Files" tab there is a category error (those tabs describe the *agent*, not the *room*) and it does nothing for `CompactApp`, which has no tab bar.

The rail is **collapsible + persisted** (`localStorage` key `probos.workspaceFiles.collapsed`), mirroring `ArtifactDrawer`'s pattern. **Default = collapsed on first run** (a thin 28px "FILES" rail with counts), diverging from `ArtifactDrawer`'s default-expanded — because the primary host (`AgentProfilePanel`) is a 420px floating panel where an expanded 300px rail would crowd the chat. The Captain expands Files on demand; the panel is resizable to make room.

### Gate = workspace room only (no Files rail on a 1:1 DM)

Render the rail **only** when the active thread is a workspace room:

```
isWorkspaceRoom(thread) ==  thread present  AND  ( thread.task_id is set   OR   >= 2 crew participants )
```

- `task_id` set ⇒ an AD-925 auto task room (authoritative "this is a workspace").
- `>= 2 crew participants` ⇒ a group room (AD-917 turns a 1:1 into a group at the 2nd crew participant).
- A 1:1 DM (one participant, no `task_id`) shows **no rail**.

Both `task_id` and `participants` are on the client-side store thread view (`AD791aChatThreadView`, verified below), so the gate is a pure function over store data.

### Outputs pane = compose the lighter `ArtifactList` (NOT the full `ArtifactDrawer`)

The rail's Outputs section composes the **presentational** `ArtifactList` (exists, AD-797) fed by a self-contained `fetchThreadArtifacts(threadId)` call. This means:
- The full **`ArtifactDrawer` is never mounted twice** — it stays exactly where it is in `CompactApp` (untouched). The rail uses a *different, lighter* component.
- The rail stays self-contained (it owns its own fetch + local state, exactly like AD-926's `InputsList` + `inputsApi` pattern), with **no coupling** to the global `selectedArtifactId` / `artifactsByThread` slice that the standalone drawer owns.
- Outputs rows are **read-only "open"** actions: selecting an artifact opens `/api/artifacts/{id}/content` in a new tab — parity with `InputsList`'s open-the-bytes model. Rich inline preview (the `ArtifactViewer`) stays the standalone drawer's job and is a forward marker (AD-929a).

### Mounts (pure assembly — reuse, do not rebuild)

| Piece | Source (verified) | How AD-929 uses it |
|---|---|---|
| Inputs list | `InputsList` (AD-926, presentational) | Rendered in the INPUTS section, fed by `fetchThreadInputs(threadId)` |
| Inputs fetch | `fetchThreadInputs` / `TaskInput` (`inputs/inputsApi.ts`) | Called by the rail on `threadId` change |
| Outputs list | `ArtifactList` (AD-797, presentational) | Rendered in the OUTPUTS section, fed by `fetchThreadArtifacts(threadId)` |
| Outputs fetch | `fetchThreadArtifacts` / `ArtifactView` (`artifacts/artifactApi.ts`) | Called by the rail on `threadId` change; click opens `/api/artifacts/{id}/content` |
| Collapse pattern | `ArtifactDrawer` localStorage idiom | New rail-scoped key `probos.workspaceFiles.collapsed` |
| Gate data | `AD791aChatThreadView.task_id` / `.participants` + `Agent.isCrew` | Pure `isWorkspaceRoom()` helper |
| Crew-count idiom | `GroupChatHeader` participant filter | Reused verbatim inside `isWorkspaceRoom` |

---

## Verified context (file:line — confirmed against HEAD `52f34cd7`)

**Hosts**
- `ui/src/CompactApp.tsx:222` — `<ArtifactDrawer />` is the **only** mount of the drawer (3rd flex column). Import at `:18`. `grep` confirms `ArtifactDrawer` appears nowhere else in `ui/src/**`.
- `ui/src/components/profile/AgentProfilePanel.tsx` — floating panel, default size `{ w: 420, h: 580 }` (`:52`), resize clamp `Math.max(320, …)` (`:157`), per-agent tab bar `TAB_LABELS` (`:15`); mounts `<ProfileChatTab>` in the chat tab (chat tab is `isCrew`-gated). **No `ArtifactDrawer` here.**

**Chat host — `ui/src/components/profile/ProfileChatTab.tsx` (1544 lines)**
- `:44` `interface Props { agentId: string; threadId?: string }`
- `:480` `const activeThreadId = useStore((s) => threadId ?? s.threadIdByAgent.get(agentId));`
- `:487` `meetingActive` selector reads `s.chatThreads.get(activeThreadId)?.metadata...meeting_active` (proof the component already subscribes to `chatThreads`).
- `:818` outer `return (` → `:819` `<div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>` … the component's single outer `</div>` closes near EOF. Children in order: `GroupChatHeader` (`:821`), `MeetingView` (`:826`), `MeetingMicButton` (`:831`), message list, composer.

**Inputs (AD-926)**
- `ui/src/components/inputs/InputsList.tsx:68` `export function InputsList(props: { inputs: TaskInput[] })` — **presentational, does NOT fetch.**
- `ui/src/components/inputs/inputsApi.ts:17` `export async function fetchThreadInputs(threadId): Promise<TaskInput[]>`; `:11` `TaskInput { content_hash; mime; filename: string|null; size: number|null; source: 'task'|'message' }`.

**Outputs (AD-797)**
- `ui/src/components/artifacts/ArtifactList.tsx:78` `export function ArtifactList(props: { artifacts: ArtifactView[]; selectedId: string|null; onSelect: (id:string)=>void })` — **presentational.**
- `ui/src/components/artifacts/artifactApi.ts:18` `export async function fetchThreadArtifacts(threadId): Promise<ArtifactView[]>`; bytes at `GET /api/artifacts/{id}/content` (`:30`).
- `ui/src/components/artifacts/ArtifactDrawer.tsx:24` `STORAGE_KEY = 'probos.artifactDrawer.collapsed'`; `:27-39` `loadCollapsedFromStorage()` (`'1'→true`, `'0'→false`, else `null`); `:63` `window.innerWidth < 1024 → collapsed` default heuristic. **Copy this load/persist shape with a new key.**

**Store — `ui/src/store/useStore.ts`**
- `:209` `interface AD791aChatThreadView { id; title; participants: string[]; …; project_id?: string|null; task_id?: string|null; metadata?: Record<string,unknown> }`
- `:250` `interface ArtifactView { id; thread_id; name; version; content_hash; mime; size_bytes; created_by; created_at; supersedes; _pinned_from_project }`
- `:336` `chatThreads: Map<string, AD791aChatThreadView>`

**Gate idiom — `ui/src/components/profile/GroupChatHeader.tsx:36-40`**
```ts
const crewParticipants = participants
  .filter((id) => id !== 'captain')
  .map((id) => ({ id, agent: agents.get(id) }))
  .filter((p): p is { id: string; agent: Agent } => !!p.agent && p.agent.isCrew);
```
`Agent.isCrew` exists (used here). **Reuse this exact filter inside `isWorkspaceRoom`.**

**No-emoji guard idiom — `ui/src/components/inputs/__tests__/InputsList.test.tsx:15`**
```ts
const EMOJI_RE = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F600}-\u{1F64F}]/u;
```

**No existing AD-929 files** (`file_search` for `*ad929*` / `*ad-929*` returns none).

---

## Implementation

Create a new `ui/src/components/workspace/` directory with the gate helper, the rail, and tests. Edit `ProfileChatTab.tsx` to mount the rail behind the gate. **No backend, no store-slice additions, no new endpoint.**

### Section 1 — `ui/src/components/workspace/isWorkspaceRoom.ts` (pure gate helper)

A pure, exported function (unit-testable in isolation; imported by `ProfileChatTab`).

- Signature: `isWorkspaceRoom(thread: AD791aChatThreadView | undefined, agents: Map<string, Agent>): boolean`
- Logic:
  - `if (!thread) return false;`
  - `if (thread.task_id) return true;`  *(truthy string ⇒ AD-925 task room)*
  - Else count crew participants using the **verbatim `GroupChatHeader:36-40` idiom** (`participants.filter(id !== 'captain').map(agents.get).filter(isCrew)`); return `crewCount >= 2`.
- Imports: `AD791aChatThreadView` from `../../store/useStore`, `Agent` from `../../store/types`.

### Section 2 — `ui/src/components/workspace/WorkspaceFilesRail.tsx` (the rail)

Self-contained component, props `{ threadId: string }`. Mirrors `ArtifactDrawer`'s collapse/persist + `InputsList`/`inputsApi` self-fetch pattern.

- **State:** local `inputs: TaskInput[]`, `artifacts: ArtifactView[]`, and rail-scoped collapsed boolean.
- **Collapse persistence:** copy `ArtifactDrawer.loadCollapsedFromStorage` shape with key `probos.workspaceFiles.collapsed` (`'1'`/`'0'`/`null`). On first run (`null`), **default collapsed = true** (divergence from the drawer; justified above). On toggle, persist `'1'`/`'0'`. Hold collapsed in local `useState` (do **not** add a store slice — keep the rail self-contained).
- **Fetch on `threadId` change** (one effect, cancellable like `ArtifactDrawer:75-92`):
  - `fetchThreadInputs(threadId)` → `setInputs(...)`; `try/catch` honest-degrade to `[]`.
  - `fetchThreadArtifacts(threadId)` → `setArtifacts(...)`; `try/catch` honest-degrade to `[]`.
- **Collapsed render:** a `flex: '0 0 28px'` rail (mirror `ArtifactDrawer:130-188`): expand chevron, vertical "FILES" label, and a count badge (`inputs.length + artifacts.length`). `data-testid="workspace-files-rail"`, `data-collapsed="true"`.
- **Expanded render:** a `flex: '0 0 300px'` rail with a header (FILES label + collapse chevron) and two scrollable sections:
  - **INPUTS** section label + `<InputsList inputs={inputs} />`.
  - **OUTPUTS** section label + `<ArtifactList artifacts={artifacts} selectedId={localSelectedId} onSelect={openArtifact} />` where `openArtifact(id)` = `window.open('/api/artifacts/' + encodeURIComponent(id) + '/content', '_blank', 'noopener')` and also sets a local `selectedId` for the row highlight.
  - `data-testid="workspace-files-rail"`, `data-collapsed="false"`.
- **HXI #3 — no emoji:** section glyphs + chevrons are **LOCAL inline stroke SVG** (`strokeWidth: 1.5`, `strokeLinecap: round`, amber `#f0b060`). **Do NOT add to `icons/Glyphs.tsx`** (the `Glyphs.test.tsx` export-count assertion bit AD-917; local inline glyphs are the established avoid-the-count-bump pattern — see `GroupChatHeader`'s local meeting SVG).
- Imports (relative from `components/workspace/`): `../inputs/InputsList`, `../inputs/inputsApi` (`fetchThreadInputs`, type `TaskInput`), `../artifacts/ArtifactList`, `../artifacts/artifactApi` (`fetchThreadArtifacts`), `ArtifactView` type from `../../store/useStore`.

### Section 3 — mount in `ProfileChatTab.tsx` (behind the gate)

1. **Imports:** add `import { WorkspaceFilesRail } from '../workspace/WorkspaceFilesRail';` and `import { isWorkspaceRoom } from '../workspace/isWorkspaceRoom';`.
2. **Selectors** (near the `activeThreadId` / `meetingActive` selectors, `:480-489`): add
   ```ts
   const workspaceThread = useStore((s) => (activeThreadId ? s.chatThreads.get(activeThreadId) : undefined));
   const agentsMap = useStore((s) => s.agents);
   const showWorkspaceFiles = !!activeThreadId && isWorkspaceRoom(workspaceThread, agentsMap);
   ```
   *(Reuse an existing `agents` selector if one is already in scope rather than adding a duplicate — grep the component first.)*
3. **Wrap the outer return in a row + add the rail as a sibling.** The current outer node (`:819`) is a `flexDirection: 'column'` filling `height: 100%`. Convert it to a row that holds the existing column (as `flex: 1, minWidth: 0`) plus the rail:
   - Change the outer `<div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>` to `<div style={{ display: 'flex', flexDirection: 'row', height: '100%' }}>`.
   - Immediately wrap **all existing children** (GroupChatHeader … composer) in an inner `<div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0, height: '100%' }}>…</div>` so the chat column is byte-identical in behavior.
   - After the inner column, add `{showWorkspaceFiles && <WorkspaceFilesRail threadId={activeThreadId} />}` (note `activeThreadId` is non-null inside the guard).
   - This is **two bracketing edits** (open + close of the body); the chat column content is unchanged.

### Section 4 — tests (see next section)

---

## Tests (Vitest only — `cd ui && npx vitest run`)

**Baseline:** AD-923 = `1208 passed | 1 skipped` (204 files); AD-926 added `InputsList.test.tsx` (+3) ⇒ current baseline ≈ **1211 passed | 1 skipped (205 files)**. **Capture the real baseline first** (`npx vitest run` before edits), then require `>= baseline + 14`.

### File 1 — `ui/src/components/workspace/__tests__/isWorkspaceRoom.test.ts` (6 tests)
Pure helper; build `AD791aChatThreadView` fixtures + a `Map<string,Agent>` (real fixtures, **not** MagicMock — BF-287). Cases:
1. `task_id` set, 0 crew → `true`.
2. no `task_id`, 2 crew participants → `true`.
3. no `task_id`, 1 crew participant (a 1:1 DM) → `false`.
4. no `task_id`, participants = `['captain', <one crew>]` → `false` (captain excluded; only 1 crew).
5. no `task_id`, 2 participants that are **non-crew** (`isCrew: false`) → `false`.
6. `thread === undefined` → `false`.

### File 2 — `ui/src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx` (8 tests)
`render` the rail; `vi.mock('../../inputs/inputsApi')` and `vi.mock('../../artifacts/artifactApi')` to return fixed `TaskInput[]` / `ArtifactView[]`; real store unnecessary (rail is self-fetching). `afterEach(cleanup)`; clear `localStorage` between tests. Cases:
1. Renders the Inputs section (`inputs-list` testid present) for a workspace room (rail expanded).
2. Renders the Outputs section (`artifact-list` testid present).
3. Calls `fetchThreadInputs(threadId)` with the passed `threadId` (assert mock called with the id).
4. Calls `fetchThreadArtifacts(threadId)` with the passed `threadId`.
5. Outputs rows: clicking an artifact row calls `window.open` with `/api/artifacts/{id}/content` (spy `window.open`).
6. Collapse toggle writes `probos.workspaceFiles.collapsed = '1'` to `localStorage` and renders `data-collapsed="true"`.
7. With `localStorage` pre-seeded `'0'`, the rail mounts **expanded** (`data-collapsed="false"`); with no value, mounts **collapsed** (default-collapsed-on-first-run).
8. No-emoji guard: `container.textContent` does not match the `EMOJI_RE` from `InputsList.test.tsx:15`.

*(The gate "a 1:1/non-workspace thread shows no panes" is fully covered by File 1 — the rail is only mounted when `isWorkspaceRoom` is true, and `ProfileChatTab` is too heavy to render whole; this matches the AD-917/921/922 precedent of testing the decision via the pure helper rather than the full chat component.)*

After Vitest: **`npm run build`** (tsc -b + vite) must be green.

---

## What this does NOT change (non-goals — do NOT build)

- **No backend / no pytest.** All endpoints exist (`/api/threads/{id}/inputs` AD-926, `/api/artifacts/thread/{id}` + `/content` AD-797). Frontend-only.
- **No `ArtifactDrawer` changes and no `CompactApp` edits.** The standalone drawer stays mounted as-is in the Yeo tray. *(The cosmetic redundancy — in `CompactApp` a workspace room would show Outputs in both the in-chat rail and the standalone drawer — is a benign, secondary-surface wart; resolving it by gating the standalone `<ArtifactDrawer />` to non-workspace threads is **forward marker AD-929b**, not this AD.)*
- **No status / "show-your-work" protocol** (that is AD-928, deferred for Captain review).
- **No presence layer** (online/working/in-meeting — future AD-930).
- **No task-level file upload** into the Inputs folder (AD-926a, deferred).
- **No inline `ArtifactViewer`** in the rail (rich preview stays the standalone drawer's job; inline preview in the rail = forward marker AD-929a).
- **No new store slice, no `Glyphs.tsx` change, no `AgentProfilePanel` tab-bar change, no facilitator/voice/meeting changes.**
- **No `ConsultationWorkspace` bridge** (AD-594a substrate stays separate — epic Decision: extend the chat-thread + ArtifactStore world).

---

## Tracking (same local commit)

- `docs/development/roadmap.md` — flip the AD-929 row to SHIPPED (gate-verified, date).
- `PROGRESS.md` — prepend the AD-929 block.
- `DECISIONS.md` — AD-929 entry: layout = in-chat Files rail (not tab bar); gate = `task_id || >=2 crew`; Outputs via lighter `ArtifactList` (drawer never double-mounted); default-collapsed; forward markers AD-929a (inline viewer) / AD-929b (CompactApp drawer gate).
- **Commit message:** `AD-929: Unified workspace view (in-chat Files rail: Inputs + Outputs)`. **COMMIT LOCAL ONLY — DO NOT PUSH.**

---

## Acceptance criteria

1. New `ui/src/components/workspace/isWorkspaceRoom.ts` exports a pure `isWorkspaceRoom(thread, agents)` returning `true` for `task_id`-set or `>=2`-crew threads, `false` for 1:1 / undefined.
2. New `ui/src/components/workspace/WorkspaceFilesRail.tsx` renders an INPUTS section (`InputsList`, fed by `fetchThreadInputs`) + an OUTPUTS section (`ArtifactList`, fed by `fetchThreadArtifacts`), collapsible + persisted under `probos.workspaceFiles.collapsed`, default-collapsed on first run, all-inline-SVG (no emoji), self-contained fetch (honest-degrade).
3. `ProfileChatTab.tsx` mounts `<WorkspaceFilesRail>` as a right rail **only when** `isWorkspaceRoom` is true; the chat column behavior is unchanged for 1:1 DMs.
4. The full `ArtifactDrawer` is **not** mounted a second time (rail uses `ArtifactList`); `CompactApp.tsx` is untouched.
5. `+14` Vitest floor across the two new test files; full suite `>= baseline + 14`, 0 new failures; `npm run build` green.
6. Committed **local only**, not pushed; trackers updated in the same commit.
7. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified against codebase (2026-06-08, HEAD `52f34cd7`)

```
ui/src/CompactApp.tsx:222                         <ArtifactDrawer />   (only mount; grep ArtifactDrawer in ui/src → CompactApp + own file)
ui/src/components/profile/AgentProfilePanel.tsx:52   const [size] default { w: 420, h: 580 }
ui/src/components/profile/AgentProfilePanel.tsx:157  Math.max(320, ... )   (resize clamp)
ui/src/components/profile/ProfileChatTab.tsx:480     const activeThreadId = useStore((s) => threadId ?? s.threadIdByAgent.get(agentId));
ui/src/components/profile/ProfileChatTab.tsx:819     <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
ui/src/components/profile/ProfileChatTab.tsx:821     {activeThreadId && <GroupChatHeader threadId={activeThreadId} />}
ui/src/components/inputs/InputsList.tsx:68           export function InputsList(props: InputsListProps)   (inputs: TaskInput[])
ui/src/components/inputs/inputsApi.ts:17             export async function fetchThreadInputs(threadId): Promise<TaskInput[]>
ui/src/components/artifacts/ArtifactList.tsx:78      export function ArtifactList(props: ArtifactListProps)   (artifacts/selectedId/onSelect)
ui/src/components/artifacts/artifactApi.ts:18        export async function fetchThreadArtifacts(threadId): Promise<ArtifactView[]>
ui/src/components/artifacts/ArtifactDrawer.tsx:24    const STORAGE_KEY = 'probos.artifactDrawer.collapsed'
ui/src/store/useStore.ts:216                         task_id?: string | null;
ui/src/store/useStore.ts:212                         participants: string[];
ui/src/store/useStore.ts:336                         chatThreads: Map<string, AD791aChatThreadView>;
ui/src/components/profile/GroupChatHeader.tsx:38     .filter((id) => id !== 'captain')   (crew-count idiom; .filter(p => p.agent.isCrew))
ui/src/components/inputs/__tests__/InputsList.test.tsx:15  const EMOJI_RE = /[\u{1F300}-\u{1FAFF}.../u   (no-emoji guard)
```
