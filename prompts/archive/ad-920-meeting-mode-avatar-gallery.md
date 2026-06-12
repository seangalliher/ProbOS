# AD-920 — Meeting mode + avatar gallery

**Phase-2 AD #1 of the "Ad-hoc Crew Collaboration (group chat → meeting)" epic.**
Promote a group chat to a live *meeting* (a MODE of the thread): a "Start Meeting" control flips `metadata.meeting_active`, and an avatar **gallery** renders every crew participant's VRM avatar at once, bound to the fleet avatar-telemetry stream. The chat thread stays the transcript. NO voice, NO STT, NO speaking/presence indicators (those are AD-921/922/923).

- **Status:** Ready to build
- **Target repo:** OSS (`d:\ProbOS`)
- **Dependencies:** AD-913 (participants), AD-914 (group fan-out), AD-915 (facilitator), AD-917 (`GroupChatHeader`/`ProfileChatTab`), AD-721 (`CrewVRM`), AD-722b-4 (`useFleetAvatarTelemetry`)
- **Current highest committed AD: AD-919 (`c8c55db3`).** Assign this work AD-920.
- **Estimated tests:** Vitest +15 floor (~17 target) across 3 files; pytest +8 floor (~10 target), 1 file.

---

## Problem

The roadmap (`docs/development/roadmap.md:375`) specifies AD-920: *"Start Meeting" promotes a group chat to a live meeting (`metadata.meeting_active`); a gallery view renders all participant VRM avatars at once, bound to the fleet avatar-telemetry stream (AD-722b-4) + `CrewVRM`; the thread remains the transcript.*

Three things are missing today:

1. **No way to persist a meeting-mode flag.** `metadata.meeting_active` does not exist on any thread. The only metadata-write path is `ChatThreadStore.set_title(thread_id, title, lock=True)` (`src/probos/threads/__init__.py:322`), which does a `BEGIN IMMEDIATE` read-modify-write merge of the JSON `metadata` column to set `title_locked`. The generic `update_thread` (`:267`) **never touches `metadata`**, `UpdateThreadRequest` (`src/probos/routers/threads.py:47`) has **no `meeting_active` field**, and the frontend `PatchThreadBody` (`ui/src/components/sidebar/threadApi.ts:90`) has **no `meeting_active` field**. → There is a real (small) backend gap; a minimal additive fix is specified in §1.

2. **No Start/End Meeting control.** `GroupChatHeader` (`ui/src/components/profile/GroupChatHeader.tsx:21`) renders rename + participant strip + add-participant, but no meeting toggle.

3. **No multi-avatar gallery.** `CrewVRM` (`ui/src/components/profile/CrewVRM.tsx:205`) renders **one** avatar inside a `<Canvas>`. `CrewAvatarPopout` wraps a single `CrewVRM` and is the only consumer — and it is **not mounted in production** (only its definition + tests exist). Nothing renders N avatars together.

---

## Solution (decisions)

| # | Decision | Why |
|---|----------|-----|
| **A — persist meeting state** | Persist `metadata.meeting_active` via a **minimal, scoped, additive** backend writer `ChatThreadStore.set_meeting_active(thread_id, active)` (RMW merge, mirrors `set_title(lock=True)`), threaded through PATCH `/api/threads/{id}` via a new `UpdateThreadRequest.meeting_active` flag. **Not** a generic arbitrary-metadata write. | Survives reload, visible to other surfaces (AD-919 `GroupChatListPanel`, AD-921/922/923), and the roadmap names `metadata.meeting_active`. Scoping the writer to one flag is Defense-in-Depth: a generic metadata PATCH would let a client clobber `created_by_agent`/`title_locked`. |
| **B — gallery structure** | New `MeetingView.tsx` iterates `thread.participants` (crew only, exclude `"captain"`), one `AvatarSlot` per participant. `AvatarSlot` renders `<Canvas><CrewVRM …/></Canvas>` when `agent.appearance?.vrm_url` is set, else `<AgentAvatarBadge …/>`. | Reuses `CrewVRM` per participant (the roadmap's prescription) and the proven `CrewAvatarPopout` `showVRM ? CrewVRM : fallback` shape. |
| **C — VRM-absent fallback** | The fallback is **`AgentAvatarBadge`** (`ui/src/components/AgentAvatarBadge.tsx:25`), NOT `ParametricAvatar`. Two triggers: (i) no `appearance.vrm_url`, (ii) `CrewVRM.onLoadError` fires (the `.vrm` asset failed to load). | VRM binaries are operator-provided/gitignored — **CI and most dev envs have zero `.vrm` files**, so nearly every slot must degrade. `AgentAvatarBadge` is a pure `<span>` (no WebGL, no R3F), so the gallery renders cleanly with no assets. `ParametricAvatar` is itself a 3D Canvas component (N of them = N WebGL contexts) — wrong fallback at gallery scale. |
| **D — control placement** | "Start/End Meeting" toggle goes in **`GroupChatHeader`** (reuses its `thread`/`agents`/`setChatThread` wiring + `crewParticipants`). Shown when `crewParticipants.length >= 1`. Uses a **local inline stroke-SVG video glyph** (NOT a `Glyphs.tsx` export). | The header already owns the thread controls. A local glyph avoids the `Glyphs.test.tsx` export-count bump (the AD-917 gotcha — that test asserts the export count). |
| **E — gallery mount** | `MeetingView` mounts **inside `ProfileChatTab`**, directly below the `GroupChatHeader` (`ui/src/components/profile/ProfileChatTab.tsx:790`), gated on `thread.metadata?.meeting_active`. | The chat is hosted per-crew-agent (`ProfileChatTab agentId=…`, thread picked via `threadId ?? threadIdByAgent.get(agentId)` at `:475` — the AD-919 host finding). Mounting the gallery in the same host is the least-invasive surface that still renders ALL participants. **No new overlay/modal/route.** |
| **F — telemetry binding** | `MeetingView` mounts `useFleetAvatarTelemetry({ onFrame })` (frames → the shared `setAvatarTelemetryFrame` store sink, keyed by `agent_id`) so the stream is live while the meeting is active, independent of whether `CognitiveCanvas` is mounted. Per-avatar `AgentSignals` come from the existing **`deriveAgentSignals(agentId, snapshot)`** (`ui/src/components/profile/avatarSignals.ts`, the production pattern at `voice.ts:323`). | "Bound to the fleet stream" + "fans out by `agent_id`" is exactly what `useFleetAvatarTelemetry` provides (AD-722b-4 docstring). v1 introduces **no** telemetry-payload→signals converter — `deriveAgentSignals` is the v1 signal source; the populated `avatarTelemetry` map is the forward-looking per-avatar binding that AD-921/923 consume. |

### Host complication (state it; do not solve it past v1)
A meeting is hosted inside ONE crew agent's `ProfileChatTab`, yet the gallery renders ALL participants. That is fine: the gallery iterates `thread.participants`, not just the host. Because `meeting_active` is **persisted on the shared thread**, opening the same group thread from any participant's profile shows the same meeting state and the same gallery. The host agent is just the mount surface (AD-919 host pattern). A single unified meeting surface independent of the host profile is an AD-923 concern — **do not build it here.**

### Known, benign concerns (note as forward markers; do not over-engineer)
- **Double fleet subscription.** If `CognitiveCanvas` is mounted behind the panel, its `useFleetAvatarTelemetry` and `MeetingView`'s both write the same idempotent store sink — two WS to a fan-out endpoint, both correct. A singleton-hook dedup is a later refinement; **do not build it.**
- **WebGL context count.** One `<Canvas>` per VRM-present participant = N contexts (browsers cap ~8–16). In CI/dev (no `.vrm`) this is **0** (all badges). Real meetings are small (2–5 crew). A shared-scene single-Canvas gallery is a future optimization — **do not build it.**

---

## Implementation

### §1 — Backend: scoped `meeting_active` metadata writer + PATCH wiring (pytest)

**1a. `src/probos/threads/__init__.py`** — add `set_meeting_active` immediately after `set_title` (after the `set_title` method ends, before `is_title_locked`). Mirror `set_title`'s `BEGIN IMMEDIATE` RMW exactly. `active=True` sets the key; `active=False` **removes** it (clean "not in a meeting"). Return the updated thread (or `None` when the row is missing) so the router can return `to_dict()`.

```python
    def set_meeting_active(
        self, thread_id: str, active: bool
    ) -> "ChatThread | None":
        """AD-920: set/clear ``metadata.meeting_active`` on a thread.

        A meeting is a live MODE of a group chat — the thread stays the
        transcript; this flag is what the UI gallery and (future) voice
        path read to know the meeting is open. Scoped writer (NOT a
        generic metadata PATCH) so callers cannot clobber sibling keys
        such as ``created_by_agent`` (AD-918) or ``title_locked``
        (AD-794). ``active=True`` sets the flag; ``active=False`` removes
        the key entirely (clean "not in a meeting"). The read-modify-
        write of the JSON ``metadata`` column uses ``BEGIN IMMEDIATE``
        for race safety, matching ``set_title(lock=True)``.

        Returns the updated thread, or ``None`` when the row is missing.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT metadata FROM chat_threads WHERE id = ?",
                    (thread_id,),
                ).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    return None
                existing: dict = {}
                if row["metadata"]:
                    try:
                        existing = json.loads(row["metadata"]) or {}
                    except (json.JSONDecodeError, TypeError):
                        existing = {}
                if active:
                    existing["meeting_active"] = True
                else:
                    existing.pop("meeting_active", None)
                conn.execute(
                    "UPDATE chat_threads SET metadata = ? WHERE id = ?",
                    (json.dumps(existing), thread_id),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return self.get_thread(thread_id)
```

**1b. `src/probos/routers/threads.py`** — add the flag to `UpdateThreadRequest` (after `title_locked`):

```python
    title_locked: bool | None = None
    # AD-920: meeting-mode flag. When non-None, routes through
    # ``store.set_meeting_active`` (a scoped metadata RMW, NOT a generic
    # metadata write). The UI sends this field on its own.
    meeting_active: bool | None = None
```

**1c. `src/probos/routers/threads.py`** — in `update_thread`, add the `meeting_active` branch at the **top of the body** (before the `title_locked` branch at `:154`), mirroring the title-lock special-case shape:

```python
    store = _get_store(runtime)
    # AD-920: meeting-mode flag is an independent, scoped metadata write
    # (RMW merge; mirrors set_title(lock=True)). The UI sends meeting_active
    # on its own, so handle it first and return the updated thread.
    if body.meeting_active is not None:
        thread = store.set_meeting_active(thread_id, body.meeting_active)
        if thread is None:
            raise HTTPException(status_code=404, detail="Thread not found")
        return thread.to_dict()
    # AD-794: when an operator-initiated rename arrives with
    # ``title_locked=True``, route the title update through
```

> The `store = _get_store(runtime)` line already exists at the top of `update_thread` — insert the `meeting_active` block right after it and before the existing `# AD-794` comment. Do **not** duplicate `_get_store`.

**1d. pytest — `tests/test_ad920_meeting_active.py`** (BF-287: real `ChatThreadStore` on a `tmp_path` DB + real FastAPI router via `TestClient` with a minimal real runtime, **no MagicMock at the store boundary**). Named cases:

Store level:
1. `test_set_meeting_active_true_writes_flag` — create thread → `set_meeting_active(id, True)` → returned thread `.metadata["meeting_active"] is True`.
2. `test_set_meeting_active_false_removes_key` — set True then False → `"meeting_active" not in metadata`.
3. `test_set_meeting_active_missing_thread_returns_none` — unknown id → `None`.
4. `test_set_meeting_active_preserves_sibling_metadata` — create with `metadata={"created_by_agent": "bones", "title_locked": True}` (AD-918 `create_thread(metadata=…)`) → `set_meeting_active(id, True)` → both siblings still present AND `meeting_active is True`.

Router level (PATCH):
5. `test_patch_meeting_active_true` — `PATCH /api/threads/{id}` `{"meeting_active": true}` → 200, body `.metadata.meeting_active is True`.
6. `test_patch_meeting_active_false_clears` — patch true then false → `meeting_active` absent.
7. `test_patch_meeting_active_missing_thread_404` — patch unknown id → 404.
8. `test_patch_meeting_active_does_not_touch_title` — create with a title, patch `{"meeting_active": true}` → title unchanged, flag set.

### §2 — Frontend API: `meeting_active` on the PATCH wrapper

**`ui/src/components/sidebar/threadApi.ts`** — extend `PatchThreadBody` and add a thin `setMeetingActive` wrapper (mirrors `addParticipant`/`removeParticipant` shape):

```typescript
export interface PatchThreadBody {
  title?: string;
  title_locked?: boolean;
  pinned?: boolean;
  archived?: boolean;
  // AD-793 (Wave 196): re-parenting threads between projects via the
  // existing PATCH endpoint (the server already supports project_id
  // per AD-791a).
  project_id?: string | null;
  // AD-920: meeting-mode flag — routes server-side through
  // store.set_meeting_active (a scoped metadata RMW).
  meeting_active?: boolean;
}
```

Add after `patchThread`:

```typescript
/**
 * AD-920: start/end meeting mode on a group thread.
 * PATCH /api/threads/{id}  body {meeting_active}  -> updated thread.to_dict()
 * (404 honest-degrades to null). The returned thread carries
 * metadata.meeting_active so the caller can setChatThread(updated).
 */
export async function setMeetingActive(
  threadId: string,
  active: boolean,
): Promise<AD791aChatThreadView | null> {
  return patchThread(threadId, { meeting_active: active });
}
```

### §3 — `GroupChatHeader`: Start/End Meeting toggle

**`ui/src/components/profile/GroupChatHeader.tsx`** — (a) import `setMeetingActive` alongside the existing `threadApi` imports; (b) read the live flag; (c) add the toggle button. Place the button in the header's action row (next to the add-participant button). Use a **local inline video glyph** (do NOT add to `Glyphs.tsx`).

- Add to the `threadApi` import: `import { patchThread, addParticipant, removeParticipant, setMeetingActive } from '../sidebar/threadApi';`
- Derive: `const meetingActive = !!(thread.metadata as Record<string, unknown> | undefined)?.meeting_active;` and gate the button on `crewParticipants.length >= 1`.
- Handler (mirror `handleAdd`):
  ```typescript
  async function handleToggleMeeting() {
    const updated = await setMeetingActive(threadId, !meetingActive);
    if (updated) setChatThread(updated);
  }
  ```
- Button (HXI #3 inline SVG; amber `#f0b060` when active, dim `#666680` when inactive; `data-testid="meeting-toggle"`; `aria-label` "Start meeting" / "End meeting"; `aria-pressed={meetingActive}`):
  ```tsx
  {crewParticipants.length >= 1 && (
    <button
      type="button"
      data-testid="meeting-toggle"
      aria-label={meetingActive ? 'End meeting' : 'Start meeting'}
      aria-pressed={meetingActive}
      title={meetingActive ? 'End meeting' : 'Start meeting'}
      onClick={() => { void handleToggleMeeting(); }}
      style={{
        background: 'none', border: 'none', cursor: 'pointer',
        color: meetingActive ? '#f0b060' : '#666680',
        display: 'inline-flex', alignItems: 'center', padding: 2,
      }}
    >
      {/* Local inline video/meeting glyph (HXI #3 — no emoji, no Glyphs.tsx
          export so the Glyphs.test.tsx count is untouched). */}
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
           stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
           strokeLinejoin="round">
        <rect x="1.5" y="4" width="9" height="8" rx="1.5" />
        <path d="M10.5 7 L14.5 5 V11 L10.5 9 Z" />
      </svg>
    </button>
  )}
  ```

### §4 — `MeetingView.tsx`: the avatar gallery (new file)

**`ui/src/components/profile/MeetingView.tsx`** (full content below). Iterates crew participants, mounts the fleet stream, renders an `AvatarSlot` per participant (VRM when present, badge fallback otherwise).

```tsx
// AD-920: meeting-mode avatar gallery. A meeting is a live MODE of a group
// chat — the thread stays the transcript; this gallery renders every crew
// participant's VRM avatar at once, bound to the AD-722b-4 fleet
// avatar-telemetry stream (fan-out by agent_id). VRM binaries are
// operator-provided/gitignored, so each slot honest-degrades to an
// AgentAvatarBadge when no .vrm is available (or fails to load). NO voice,
// NO speaking/presence indicators (AD-921/923). HXI #3 — inline SVG only,
// amber palette, no emoji.
import { useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { useStore } from '../../store/useStore';
import type { Agent } from '../../store/types';
import { CrewVRM } from './CrewVRM';
import { deriveAgentSignals } from './avatarSignals';
import { AgentAvatarBadge } from '../AgentAvatarBadge';
import { useFleetAvatarTelemetry } from '../../avatars/useFleetAvatarTelemetry';

const CAPTAIN_PARTICIPANT_ID = 'captain';

/** One gallery cell: a live VRM when the agent has one, else a badge. */
function AvatarSlot({ agentId }: { agentId: string }) {
  const agent = useStore((s) => s.agents.get(agentId)) as Agent | undefined;
  const [loadFailed, setLoadFailed] = useState(false);
  const vrmUrl = agent?.appearance?.vrm_url;
  const showVRM = !!vrmUrl && !loadFailed;
  const dept = (agent as (Agent & { department?: string }) | undefined)?.department ?? '';
  const callsign = agent?.callsign ?? agentId;

  return (
    <div
      data-testid={`avatar-slot-${agentId}`}
      style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
        width: 120, height: 160,
      }}
    >
      <div style={{ width: 112, height: 132, position: 'relative' }}>
        {showVRM ? (
          <Canvas camera={{ position: [0, 1.45, 0.85], fov: 28 }} flat frameloop="always">
            <ambientLight intensity={0.4} />
            <directionalLight position={[1, 2, 2]} intensity={0.6} />
            <CrewVRM
              vrmUrl={vrmUrl!}
              agentId={agentId}
              expressionOverrides={agent?.appearance?.expression_overrides ?? {}}
              signals={deriveAgentSignals(agentId, useStore.getState())}
              onLoadError={() => setLoadFailed(true)}
              restingExpression={agent?.appearance?.dsl?.expression_resting ?? null}
            />
          </Canvas>
        ) : (
          <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <AgentAvatarBadge agentId={agentId} callsign={callsign} department={dept} size={32} />
          </div>
        )}
      </div>
      <span
        data-testid={`avatar-caption-${agentId}`}
        style={{ color: '#e0dcd4', fontSize: 11, fontWeight: 600, maxWidth: 112,
                 overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
      >
        {callsign}
      </span>
    </div>
  );
}

export function MeetingView({ threadId }: { threadId: string }) {
  const thread = useStore((s) => s.chatThreads.get(threadId));
  const agents = useStore((s) => s.agents);
  const setAvatarTelemetryFrame = useStore((s) => s.setAvatarTelemetryFrame);

  // Bind to the fleet avatar-telemetry stream while the meeting is open
  // (AD-722b-4 fans out by agent_id). Idempotent with the CognitiveCanvas
  // sink; guarantees liveness even when the canvas is unmounted. v1 reads
  // signals via deriveAgentSignals; the populated avatarTelemetry map is
  // the forward-looking per-avatar binding consumed by AD-921/923.
  useFleetAvatarTelemetry({
    onFrame: (frame) => setAvatarTelemetryFrame(frame.agent_id, frame.type, frame.payload),
  });

  if (!thread) return null;

  const crewIds = (thread.participants ?? [])
    .filter((id) => id !== CAPTAIN_PARTICIPANT_ID)
    .filter((id) => agents.get(id)?.isCrew);

  return (
    <div
      data-testid="meeting-view"
      style={{
        display: 'flex', flexWrap: 'wrap', gap: 12, justifyContent: 'center',
        padding: 12, borderBottom: '1px solid rgba(240,176,96,0.15)',
        background: 'rgba(240,176,96,0.04)',
      }}
    >
      {crewIds.length === 0 ? (
        <span style={{ color: '#666680', fontSize: 12 }}>No crew in this meeting yet.</span>
      ) : (
        crewIds.map((id) => <AvatarSlot key={id} agentId={id} />)
      )}
    </div>
  );
}
```

> **Verify before writing:** confirm `Agent.appearance.dsl?.expression_resting` exists on the store type. `CrewAvatarPopout.tsx:294` reads `appearance?.dsl?.expression_resting`, and `Agent.appearance.dsl?: AvatarDSLDict | null` is on the store type (`ui/src/store/types.ts:370`). If `expression_resting` is not a field on `AvatarDSLDict`, pass `restingExpression={null}` instead — it is optional on `CrewVRM`.

### §5 — `ProfileChatTab`: mount the gallery under the header

**`ui/src/components/profile/ProfileChatTab.tsx`** — (a) `import { MeetingView } from './MeetingView';` alongside the `GroupChatHeader` import (`:34`); (b) mount it right below the header (`:790`), gated on the persisted flag:

```tsx
      {/* AD-917: in-chat group controls (rename / participants / add). Renders
          nothing until a thread exists. Mounted above the message list. */}
      {activeThreadId && <GroupChatHeader threadId={activeThreadId} />}
      {/* AD-920: meeting-mode avatar gallery — mounted below the controls when
          the thread is in a meeting (metadata.meeting_active). The thread
          remains the transcript below. */}
      {activeThreadId &&
        !!(useStore.getState().chatThreads.get(activeThreadId)?.metadata as Record<string, unknown> | undefined)?.meeting_active && (
          <MeetingView threadId={activeThreadId} />
        )}
```

> Prefer a reactive selector over `getState()` so the gallery mounts/unmounts as the flag changes. If the file already selects the active thread reactively, gate on that. A clean reactive form:
> ```tsx
> const meetingActive = useStore((s) =>
>   !!(activeThreadId && (s.chatThreads.get(activeThreadId)?.metadata as Record<string, unknown> | undefined)?.meeting_active),
> );
> // …
> {activeThreadId && meetingActive && <MeetingView threadId={activeThreadId} />}
> ```
> Use the reactive form. Place the `meetingActive` selector next to the existing `activeThreadId` selector (`:475`).

---

## Tests

### Vitest — run with `cd ui && npx vitest run`

**§4 gallery — `ui/src/components/profile/__tests__/MeetingView.test.tsx`** (~8). Mock R3F + `CrewVRM` + the fleet hook per the **canonical `CrewAvatarPopout.test.tsx` pattern** (no WebGL, no `.vrm`); seed the store with `useStore.setState` (real store, BF-287):

```typescript
vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: any) => <div data-testid="canvas">{children}</div>,
  useFrame: () => {},
}));
vi.mock('../../../avatars/useFleetAvatarTelemetry', () => ({
  useFleetAvatarTelemetry: (_opts: any) => {},
}));
vi.mock('../CrewVRM', () => ({
  CrewVRM: (props: any) => {
    // expose onLoadError so a test can trigger the .vrm-absent fallback
    crewVrmMock.lastOnLoadError = props.onLoadError;
    crewVrmMock.renderedAgentIds.push(props.agentId);
    return <div data-testid={`crew-vrm-${props.agentId}`} />;
  },
}));
```

Cases:
1. `renders one slot per crew participant; excludes captain + non-crew` — thread `participants: ['captain', 'echo', 'bones', 'ext']`, where `echo`/`bones` are `isCrew`, `ext` is not → 2 `avatar-slot-*` testids (`echo`, `bones`), none for `captain`/`ext`.
2. `renders CrewVRM when the agent has appearance.vrm_url` — seed `echo` with `appearance.vrm_url='/avatars/echo.vrm'` → `crew-vrm-echo` present.
3. `renders AgentAvatarBadge when appearance is absent` — `bones` has no `appearance` → `agent-avatar-badge` present in the `bones` slot, no `crew-vrm-bones`.
4. `falls back to badge when CrewVRM onLoadError fires` — `echo` with vrm_url renders `CrewVRM`; call `crewVrmMock.lastOnLoadError()`, rerender → `echo` slot now shows the badge.
5. `renders the empty-state when no crew participants` — thread `participants: ['captain']` → `meeting-view` present, `No crew in this meeting yet.`
6. `caption shows the callsign` — `avatar-caption-echo` text equals echo's callsign.
7. `returns null when the thread is missing` — `threadId` not in store → `meeting-view` absent.
8. `no-emoji guard` — `expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u)`.

**§3 header toggle — `ui/src/components/profile/__tests__/GroupChatHeader.meeting.test.tsx`** (~5). Separate file (do NOT extend the existing `GroupChatHeader.test.tsx` — keep its count stable). Mock `../sidebar/threadApi` (`setMeetingActive`, plus `patchThread`/`addParticipant`/`removeParticipant` as no-op stubs the header imports); real store via `useStore.setState`:
1. `start meeting → setMeetingActive(threadId, true) + setChatThread` — thread not in a meeting, `>=1` crew → click `meeting-toggle` → `setMeetingActive` called with `(threadId, true)`; mock returns an updated thread → store reflects it.
2. `end meeting → setMeetingActive(threadId, false)` — thread with `metadata.meeting_active=true` → click → called with `(threadId, false)`.
3. `button aria-pressed reflects metadata.meeting_active` — active thread → `aria-pressed="true"`; inactive → `"false"`.
4. `toggle hidden when no crew participants` — `participants: ['captain']` → no `meeting-toggle`.
5. `no-emoji guard`.

**§2 api — `ui/src/components/sidebar/__tests__/threadApi.meeting.test.ts`** (~3). Mock `global.fetch`:
1. `setMeetingActive PATCHes /api/threads/{id} with {meeting_active}` — assert URL, method `PATCH`, body `{ meeting_active: true }`.
2. `returns the updated thread on ok` — fetch resolves `{ id, metadata: { meeting_active: true }, … }` → returned view has `id`.
3. `returns null on !ok` — fetch `{ ok: false }` → `null`.

### pytest — run with `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad920_meeting_active.py -q -n 0`
The 8 cases in §1d.

### Gates
- Focused: `cd ui && npx vitest run src/components/profile/__tests__/MeetingView.test.tsx src/components/profile/__tests__/GroupChatHeader.meeting.test.tsx src/components/sidebar/__tests__/threadApi.meeting.test.ts` (all green) + the pytest file (8 green).
- UI build: `cd ui && npm run build` (`tsc -b` + vite) green.
- Blast radius: `cd ui && npx vitest run` (full UI suite green, +~16 vs the AD-919 baseline of 1142 pass / 1 skip) and `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "thread or chat" -q -n 0` green.

---

## Do NOT build (explicit non-goals)
- **NO voice** — no TTS, no per-agent voice playback, no sequenced speaking turns (AD-921).
- **NO Captain STT / VAD / push-to-talk** (AD-922).
- **NO speaking/presence indicators** — no who's-speaking highlight, no join/leave animation, no raise-hand, no lip-sync driven by the meeting, no transcript/summary writeback on meeting end (AD-923).
- **NO telemetry-payload → AgentSignals converter.** v1 signals come from `deriveAgentSignals`; the `avatarTelemetry` map is populated but not yet mapped to per-avatar expression (AD-921/923).
- **NO generic metadata PATCH.** Only the scoped `set_meeting_active` writer. Do not add an arbitrary `metadata` field to `UpdateThreadRequest`/`update_thread`.
- **NO `ParametricAvatar` in the gallery** (it's a 3D Canvas; the badge is the gallery-scale fallback).
- **NO new overlay/modal/route, no full-screen meeting surface, no unified host-independent meeting view** (AD-923).
- **NO `Glyphs.tsx` change** (use a local inline glyph; avoid the `Glyphs.test.tsx` count bump).
- **NO `CrewAvatarPopout` change, no `CognitiveCanvas` change, no singleton-hook dedup, no shared-Canvas gallery refactor.**
- **NO new config field, no new agent/pool, no consensus, no `events.py` change.**

## What this does NOT change
`Glyphs.tsx`/`Glyphs.test.tsx`, `CrewAvatarPopout.tsx` (+ its tests), `CognitiveCanvas.tsx`, `ParametricAvatar.tsx`, `useFleetAvatarTelemetry.ts`, `avatarSignals.ts`, `CrewVRM.tsx`, the AD-914 fan-out, the AD-915 facilitator, `create_thread`/`update_thread` generic shape (only the additive `meeting_active` branch + new `set_meeting_active`), the existing `GroupChatHeader.test.tsx`/`threadApi.participants.test.ts`/`ProfileChatTab.groupsend.test.tsx`.

## Tracking
- `docs/development/roadmap.md` AD-920 row → "SHIPPED <date> gate-verified".
- `PROGRESS.md` → prepend an AD-920 block.
- `DECISIONS.md` → add an AD-920 entry (above AD-919): scoped `set_meeting_active` metadata writer + `MeetingView` gallery + `deriveAgentSignals` v1 signal source + `AgentAvatarBadge` VRM-absent fallback + decisions A–F.
- Staging: stage **only** the explicit changed paths (NOT `git add -A`); run the cached-deletion audit before commit. Do not push.

## Acceptance criteria
1. `ChatThreadStore.set_meeting_active` sets/clears `metadata.meeting_active` via a `BEGIN IMMEDIATE` RMW that preserves sibling keys; returns the updated thread or `None`.
2. `PATCH /api/threads/{id}` with `{"meeting_active": true|false}` writes/clears the flag and returns `to_dict()` (404 on missing thread).
3. `setMeetingActive` (frontend) PATCHes with `{meeting_active}` and returns the updated thread.
4. `GroupChatHeader` shows a Start/End Meeting toggle (local inline SVG, amber-when-active, `aria-pressed` reflects the flag) when `crewParticipants.length >= 1`; clicking flips `metadata.meeting_active` and updates the store.
5. `MeetingView` renders one slot per crew participant (excludes `"captain"`/non-crew), a `CrewVRM` when `appearance.vrm_url` is present, and an `AgentAvatarBadge` fallback when the VRM is absent OR `onLoadError` fires; it binds to the fleet stream via `useFleetAvatarTelemetry`.
6. `ProfileChatTab` mounts `MeetingView` below `GroupChatHeader` only when `metadata.meeting_active` is truthy; the message-list transcript stays.
7. All R3F/VRM tests pass with **no WebGL context and no `.vrm` asset** (mocked per the `CrewAvatarPopout.test.tsx` precedent); no-emoji guard on every new UI test.
8. Vitest +15 floor (3 files) green; pytest +8 (1 file) green; `npm run build` green; full UI + thread/chat pytest blast radius green.
9. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-07)

```
git rev-parse --short HEAD
  c8c55db3   (AD-919 — current highest committed AD)

# Fleet telemetry hook (AD-722b-4) — signature, frame shape, fan-out by agent_id
ui/src/avatars/useFleetAvatarTelemetry.ts:7    export interface FleetTelemetryFrame { type; agent_id; payload }
ui/src/avatars/useFleetAvatarTelemetry.ts:19   export function useFleetAvatarTelemetry({ onFrame, enabled=true, url })
ui/src/avatars/useFleetAvatarTelemetry.ts:64   deriveFleetUrl -> /api/agent/avatar-telemetry/stream
ui/src/components/CognitiveCanvas.tsx:71        useFleetAvatarTelemetry({ onFrame: f => setAvatarTelemetryFrame(f.agent_id, f.type, f.payload) })

# CrewVRM — props, Canvas-bound (useFrame), onLoadError on .vrm failure
ui/src/components/profile/CrewVRM.tsx:205       export function CrewVRM({ vrmUrl, agentId, expressionOverrides, signals, onLoadError, restingExpression?, bodyState? })
ui/src/components/profile/CrewVRM.tsx:11         import { useFrame } from '@react-three/fiber'   (must be inside <Canvas>)
ui/src/components/profile/CrewVRM.tsx:336/356    onLoadError() on missing vrm / load error
ui/src/components/profile/CrewVRM.tsx:330        bare filename resolves -> /api/system/avatars/{vrmUrl}

# Single-avatar precedent + fallback shape (NOT mounted in production)
ui/src/components/profile/CrewAvatarPopout.tsx:59   export function CrewAvatarPopout({ agentId, appearance, departmentColor, agentSignals, onClose, ... })
ui/src/components/profile/CrewAvatarPopout.tsx:289   showVRM ? <CrewVRM/> : <ParametricAvatar/>   (inside <Canvas>)

# Badge fallback (pure span, no R3F) + AgentSignals + deriveAgentSignals
ui/src/components/AgentAvatarBadge.tsx:25        export function AgentAvatarBadge({ agentId, callsign, department='', size=24|32 })
ui/src/components/profile/avatarSignals.ts:19    interface AgentSignals { trust_delta; load; working_state:'idle'|'responding'|'blocked'; tier3_alert }
ui/src/components/profile/avatarSignals.ts:33    export function deriveAgentSignals(agentId, storeSlice) -> AgentSignals
ui/src/audio/voice.ts:323                        deriveAgentSignals(agent_id, store)   (production usage)

# Store wiring
ui/src/store/useStore.ts:324                     avatarTelemetry: Map<string, Record<string, unknown>>
ui/src/store/useStore.ts:919                     setAvatarTelemetryFrame(agent_id, type, payload)
ui/src/store/useStore.ts:470 / :1259             setChatThread(thread: AD791aChatThreadView)
ui/src/store/useStore.ts:223                      AD791aChatThreadView.metadata?: Record<string, unknown>
ui/src/store/types.ts:357                         Agent.isCrew: boolean   (+ callsign)
ui/src/store/types.ts:365                         Agent.appearance?: { vrm_url; expression_overrides; color_palette_hint; dsl? }
ui/src/store/types.ts:370                         appearance.dsl?: AvatarDSLDict | null

# Header + mount host
ui/src/components/profile/GroupChatHeader.tsx:21    GroupChatHeader({ threadId }) — reads thread/agents/setChatThread, computes crewParticipants
ui/src/components/profile/GroupChatHeader.tsx:13     import { patchThread, addParticipant, removeParticipant } from '../sidebar/threadApi'
ui/src/components/profile/ProfileChatTab.tsx:475    activeThreadId = threadId ?? s.threadIdByAgent.get(agentId)
ui/src/components/profile/ProfileChatTab.tsx:790    {activeThreadId && <GroupChatHeader threadId={activeThreadId} />}   (gallery mounts below)

# threadApi PATCH wrapper (GAP: PatchThreadBody has no meeting_active)
ui/src/components/sidebar/threadApi.ts:90          interface PatchThreadBody { title?; title_locked?; pinned?; archived?; project_id? }   (no meeting_active)
ui/src/components/sidebar/threadApi.ts:99          patchThread(threadId, body) -> AD791aChatThreadView | null   (PATCH /api/threads/{id})

# Backend metadata-write gap + the precedent to mirror
src/probos/routers/threads.py:47                   class UpdateThreadRequest   (title/pinned/archived/.../title_locked — NO meeting_active)
src/probos/routers/threads.py:143                  async def update_thread(...)   (title_locked special-case at :154 -> set_title(lock=True))
src/probos/threads/__init__.py:267                 def update_thread(...)   (generic col UPDATE — never touches metadata)
src/probos/threads/__init__.py:322                 def set_title(thread_id, title, *, lock=False)   (BEGIN IMMEDIATE metadata RMW — THE precedent)
src/probos/threads/__init__.py:109/126             ChatThread.metadata: dict = field(default_factory=dict)  /  to_dict()["metadata"]
src/probos/threads/__init__.py:193                 create_thread(..., metadata: dict | None = None)   (AD-918 — used by pytest case 4)

# R3F/VRM test mock precedent (no WebGL, no .vrm)
ui/src/__tests__/CrewAvatarPopout.test.tsx:11      vi.mock('@react-three/fiber', () => ({ Canvas: ({children}) => <div>{children}</div>, useFrame: () => {} }))
ui/src/__tests__/CrewAvatarPopout.test.tsx:19      vi.mock('../components/profile/CrewVRM', ...)  (stub div)
ui/src/__tests__/CognitiveCanvas.fleetHook.test.tsx:7   vi.mock('../avatars/useFleetAvatarTelemetry', ...)

# Roadmap
docs/development/roadmap.md:371                     Phase 2 — meeting mode block
docs/development/roadmap.md:375                     AD-920 row (metadata.meeting_active + gallery + fleet stream + CrewVRM)
```
