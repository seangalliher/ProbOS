# AD-923 — Meeting presence + speaking indicator + transcript writeback

**Status:** Ready to build
**Dependencies:** AD-920 (MeetingView + GroupChatHeader End toggle + `set_meeting_active`), AD-921 (`useMeetingVoice.speakingAgentId`), AD-922 (`speakingAgentId` already consumed by the echo gate)
**Estimated tests:** +14 Vitest (3 new files), **0 pytest** (no backend change)
**Highest committed AD:** **AD-922 (`93d63e9b`, git HEAD)** — verified `git log --oneline -3`
**Target repo:** OSS (`d:\ProbOS`)
**Epic:** Ad-hoc Crew Collaboration (group chat → meeting). **This is the FINAL AD (AD-913 → AD-923). It closes the epic.**

---

## Roadmap scope (canonical — `docs/development/roadmap.md:378`)

> AD-923 | Meeting presence + speaking indicator — who's-speaking highlight in the gallery, join/leave, raise-hand/turn signaling (HXI #4 motion = state); meeting end writes a transcript/summary back to the thread | Meeting mode | 3

Three parts:
1. **Who's-speaking highlight** — the gallery avatar for `speakingAgentId` gets a visible active treatment (amber ring + pulse — HXI #4 motion=state); the others dim. The visual completion of the "video call" feel.
2. **Presence** — render who is in the meeting (participants already render via AD-920; AD-923 adds a small presence/roster header + a Captain-present chip). Join/leave is already reflected (the gallery re-renders on `thread.participants` change).
3. **Transcript writeback on End** — when the meeting ends (AD-920 End toggle), append a **deterministic `system` message** to the thread via the existing `POST /api/threads/{id}/messages` endpoint, then clear `meeting_active`.

---

## Verified context (read first — all file:line refs are REAL, grep-confirmed 2026-06-07)

### The speaking signal already reaches the mount site (clean seam — NO new wiring)
- `ui/src/audio/useMeetingVoice.ts` — `useMeetingVoice({ meetingActive }): { speakReplies, speakingAgentId }`. `speakingAgentId: string | null` (`null` between utterances / idle) is the **AD-923 indicator seam** (interface at `useMeetingVoice.ts:31`; returned at `:73`).
- `ui/src/components/profile/ProfileChatTab.tsx:491` — `const { speakReplies: speakMeetingReplies, speakingAgentId } = useMeetingVoice({ meetingActive });` — **`speakingAgentId` is already destructured and in scope** (AD-921/922).
- `ProfileChatTab.tsx:826` — `{activeThreadId && meetingActive && <MeetingView threadId={activeThreadId} />}` — the mount site. `speakingAgentId` is in scope here → **pass it as a prop**. (`:836` already passes `speaking={speakingAgentId != null}` to `MeetingMicButton`, proving the value is live at this point in the render.)

### MeetingView — the highlight is a WRAPPER treatment (NO CrewVRM change)
- `ui/src/components/profile/MeetingView.tsx:80` — `export function MeetingView({ threadId }: { threadId: string })`.
- `MeetingView.tsx` (render) — `crewIds.map((id) => <AvatarSlot key={id} agentId={id} />)`. `crewIds` = `thread.participants` minus `CAPTAIN_PARTICIPANT_ID` ('captain', `:17`) minus non-crew.
- `MeetingView.tsx:21` — `function AvatarSlot({ agentId }: { agentId: string })`. Slot root has `data-testid={\`avatar-slot-${agentId}\`}`; caption has `data-testid={\`avatar-caption-${agentId}\`}`.
- **The highlight seam** = the inner avatar container `<div style={{ width: 112, height: 132, position: 'relative' }}>` inside `AvatarSlot` (the div that wraps either the `<Canvas><CrewVRM/></Canvas>` or the `<AgentAvatarBadge/>`). A `boxShadow` ring + `animation` + `opacity` on **this div** highlights/dims the avatar **without touching `CrewVRM`**.

### HXI pulse idiom (reuse — do NOT invent a new one)
- `ui/src/components/crew/CrewCollaborationPanel.tsx:186-191` — the canonical co-located `<style>` + `@keyframes crewSubtaskPulse` + `.crew-subtask-pulse { animation: crewSubtaskPulse 1.6s ease-in-out infinite; }` pattern. Many siblings do the same (`GamePanel.tsx`, `WakeWordIndicator.tsx`, `CognitiveCanvas.tsx:97`, `IntentSurface.tsx:2426`). Mirror it for `meetingSpeakingPulse`.

### Transcript writeback — the message-append path (existing; NO backend change)
- `src/probos/routers/threads.py:69-78` — `AppendMessageRequest`: `author_id` (`min_length=1`), **`role: str = Field(..., pattern="^(captain|agent|system)$")`** (**`system` is already valid**), `body` (`min_length=1`), `metadata: dict | None`, `attachment_ids` (optional).
- `threads.py:228` — `async def append_message(...)` → `store.append_message(thread_id, author_id=, role=, body=, metadata=)` (`:257`).
- `threads.py:291` — the AD-914 group fan-out is gated `if body.role == "captain":` → **a `role:"system"` append does NOT fan out** (no agent dispatch, no `per_agent_replies`). Exactly what we want for an end-of-meeting marker.
- `ui/src/components/profile/ProfileChatTab.tsx:616-625` — the existing group-send already POSTs `/api/threads/${id}/messages` with `{ author_id:'captain', role:'captain', body, attachment_ids }`. The writeback **mirrors this fetch shape** with `role:'system'`.

### The End toggle — where the writeback fires
- `ui/src/components/profile/GroupChatHeader.tsx:12` — `import { patchThread, addParticipant, removeParticipant, setMeetingActive } from '../sidebar/threadApi';` (**add `appendMessage`**).
- `GroupChatHeader.tsx` — `const meetingActive = !!(thread.metadata as ...)?.meeting_active;`
- `GroupChatHeader.tsx` — `crewParticipants` = `{ id, agent }[]` filtered to crew (`agent.callsign` available — used for the marker text + count).
- `GroupChatHeader.tsx` (the hook site) —
  ```ts
  async function handleToggleMeeting() {
    const updated = await setMeetingActive(threadId, !meetingActive);
    if (updated) setChatThread(updated);
  }
  ```
  On **End** (`meetingActive === true`), append the marker **before** `setMeetingActive(false)`, then clear. (`setMeetingActive` is purely client→`PATCH /api/threads/{id}` per AD-920 — confirmed `threadApi.ts:setMeetingActive` → `patchThread(threadId, { meeting_active })`.)

### threadApi — no message-append wrapper exists yet
- `ui/src/components/sidebar/threadApi.ts` — has `listThreads / searchThreads / createThread / patchThread / setMeetingActive / deleteThread / addParticipant / removeParticipant`. **No `appendMessage`.** Add a thin one (mirrors the others; Tier-2 honest-degrade → `null`).

### Test idioms to mirror
- `ui/src/components/profile/__tests__/MeetingView.test.tsx` — mocks `@react-three/fiber` (`Canvas`→div, `useFrame`→{}), `useFleetAvatarTelemetry`, `CrewVRM` (stub div recording `agentId`); seeds the REAL store via `useStore.setState` (BF-287); `mkAgent`/`mkThread` fixtures; no-emoji guard via `container.innerHTML`.
- `ui/src/components/profile/__tests__/GroupChatHeader.meeting.test.tsx` — `vi.mock('../../sidebar/threadApi', ...)` with the wrappers as `vi.fn()`; seeds real store; `fireEvent.click(screen.getByTestId('meeting-toggle'))`.
- `ui/src/components/sidebar/__tests__/threadApi.meeting.test.ts` — `vi.stubGlobal('fetch', vi.fn()...)`; asserts URL + method + serialized body; `\p{Extended_Pictographic}/u` no-emoji guard on the body.

---

## Design

### Part 1 — Who's-speaking highlight (MeetingView)
1. `MeetingView` gains an **optional** prop: `speakingAgentId?: string | null` (default `undefined`/`null` → existing AD-920 `MeetingView.test.tsx` renders, which mount `<MeetingView threadId=... />`, stay green).
2. Thread it per-slot: `<AvatarSlot key={id} agentId={id} speaking={id === speakingAgentId} someoneSpeaking={speakingAgentId != null} />`.
3. `AvatarSlot` gains optional `speaking?: boolean` (default `false`) and `someoneSpeaking?: boolean` (default `false`). Apply the treatment to the **inner avatar container div** (`width:112,height:132`):
   - `speaking` → amber ring + pulse: `boxShadow: '0 0 0 2px #f0b060, 0 0 12px rgba(240,176,96,0.55)'`, `borderRadius: 8`, `animation: 'meetingSpeakingPulse 1.6s ease-in-out infinite'`, `opacity: 1`.
   - `!speaking && someoneSpeaking` → dim: `opacity: 0.5`, no ring/animation.
   - `!someoneSpeaking` (idle) → neutral: `opacity: 1`, no ring/animation.
   - Add `data-speaking={speaking ? 'true' : 'false'}` to the **slot root** (`avatar-slot-${agentId}`) for a clean, jsdom-safe test assertion.
4. Inject a co-located `<style>` once in `MeetingView` with `@keyframes meetingSpeakingPulse` (mirror `CrewCollaborationPanel.tsx:186-191` — e.g. `0%,100% { box-shadow: 0 0 0 2px #f0b060, 0 0 8px rgba(240,176,96,0.4); } 50% { box-shadow: 0 0 0 2px #f0b060, 0 0 16px rgba(240,176,96,0.8); }`). Browser-real motion; jsdom ignores the animation but the inline style/attr is asserted. **HXI #4 motion=state, amber, inline CSS, no emoji.**

### Part 2 — Presence (MeetingView)
5. Add a small presence header inside `MeetingView` (above the gallery), `data-testid="meeting-presence"`: the crew count + a Captain-present chip (the Captain is the viewer; they are always present when the gallery shows). Deterministic text, e.g. `{crewIds.length} in meeting` + a `data-testid="captain-present"` chip reading `You (Captain)`. No emoji; amber/dim palette. (Join/leave needs **no new code** — the gallery already re-renders on `thread.participants` change.)

### Part 3 — Transcript writeback (threadApi + GroupChatHeader)
6. **`threadApi.ts`** — add a thin transport wrapper after `removeParticipant`:
   ```ts
   export interface AppendMessageBody {
     author_id: string;
     role: 'captain' | 'agent' | 'system';
     body: string;
     metadata?: Record<string, unknown>;
     attachment_ids?: string[];
   }
   /**
    * AD-923: append a message to a thread.
    * POST /api/threads/{id}/messages -> appended message dict (or null on failure).
    * Tier-2 honest-degrade: a network/!ok failure returns null so callers can
    * continue (e.g. still end the meeting even if the marker append failed).
    */
   export async function appendMessage(
     threadId: string,
     body: AppendMessageBody,
   ): Promise<Record<string, unknown> | null> {
     try {
       const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}/messages`, {
         method: 'POST',
         headers: { 'Content-Type': 'application/json' },
         body: JSON.stringify(body),
       });
       if (!res.ok) return null;
       return (await res.json()) as Record<string, unknown>;
     } catch {
       return null;
     }
   }
   ```
7. **`GroupChatHeader.tsx`** — on **End only**, compose a deterministic marker and append it **before** clearing `meeting_active`. Honest-degrade: a failed append must NOT block ending the meeting.
   ```ts
   async function handleToggleMeeting() {
     // AD-923: ending a meeting writes a deterministic end-of-meeting marker
     // into the thread transcript (the thread IS the transcript) before the
     // flag is cleared. Honest-degrade: appendMessage -> null never blocks End.
     if (meetingActive) {
       const n = crewParticipants.length;
       const names = crewParticipants.map((p) => p.agent.callsign).join(', ');
       const marker = names
         ? `Meeting ended — ${n} participant${n === 1 ? '' : 's'}: ${names}.`
         : `Meeting ended — ${n} participants.`;
       await appendMessage(threadId, {
         author_id: 'system',
         role: 'system',
         body: marker,
         metadata: { meeting_end: true, participant_count: n },
       });
     }
     const updated = await setMeetingActive(threadId, !meetingActive);
     if (updated) setChatThread(updated);
   }
   ```
   The marker is **deterministic, client-side, no LLM, no backend**. (`role:'system'` skips the `role=="captain"` fan-out gate at `threads.py:291`.) Persisted server-side → visible on next thread load.

### Part 4 — Thread the prop in (ProfileChatTab, one line)
8. `ProfileChatTab.tsx:826` — `<MeetingView threadId={activeThreadId} speakingAgentId={speakingAgentId} />`. `speakingAgentId` is already destructured at `:491` and used at `:836` — no other change.

---

## Step-by-step

1. **`ui/src/components/sidebar/threadApi.ts`** — add `AppendMessageBody` + `appendMessage` (Part 3 step 6).
2. **`ui/src/components/profile/MeetingView.tsx`** — add the optional `speakingAgentId` prop on `MeetingView`; add optional `speaking`/`someoneSpeaking` on `AvatarSlot`; apply the ring/pulse/dim to the inner container + `data-speaking` on the slot root; inject the `@keyframes meetingSpeakingPulse` `<style>`; add the `meeting-presence` header + `captain-present` chip (Parts 1 + 2).
3. **`ui/src/components/profile/GroupChatHeader.tsx`** — import `appendMessage`; add the End-only marker append before `setMeetingActive(false)` (Part 3 step 7).
4. **`ui/src/components/profile/ProfileChatTab.tsx`** — pass `speakingAgentId` to `MeetingView` (one line, Part 4).
5. Tests (3 new files, below).
6. Trackers: roadmap AD-923 row → SHIPPED; `PROGRESS.md` block; `DECISIONS.md` AD-923 entry. **Epic-complete note.**

---

## Tests (Vitest only — `cd ui && npx vitest run`)

**First capture the real baseline** (`cd ui && npx vitest run` at HEAD `93d63e9b`) and record it; AD-921 was `1177/1`, AD-922 added the meeting-mic suite (~`1191/1`). Floor target = baseline **+14**.

### `ui/src/components/profile/__tests__/MeetingView.speaking.test.tsx` (6) — mirror `MeetingView.test.tsx` mocks (R3F + CrewVRM stub + fleet hook + real-store BF-287)
1. **Speaking slot lit** — seed thread with crew `a1,a2`; render `<MeetingView threadId speakingAgentId="a1" />`; assert `avatar-slot-a1` has `data-speaking="true"`.
2. **Others dim** — same render; assert `avatar-slot-a2` has `data-speaking="false"` (and that the non-speaking inner container carries the dim style, e.g. `opacity` 0.5 — assert via the inner element's style or a `data-dim` marker).
3. **Idle: nobody lit** — render with `speakingAgentId={null}`; assert both slots `data-speaking="false"` and neither dimmed.
4. **Presence renders all crew** — assert a slot exists per crew participant (captain + non-crew excluded, mirroring AD-920) and `meeting-presence` shows the count.
5. **Captain-present chip** — assert `captain-present` testid renders.
6. **No-emoji guard** — `container.innerHTML` (incl. the injected `<style>`) has no `\p{Extended_Pictographic}/u`.

### `ui/src/components/profile/__tests__/GroupChatHeader.transcript.test.tsx` (4) — mirror `GroupChatHeader.meeting.test.tsx` (mock `../../sidebar/threadApi` incl. `appendMessage`; real-store seed)
1. **End writes a system marker** — seed thread `meeting_active:true` with 2 crew; mock `setMeetingActive` → resolved updated thread; `fireEvent.click(meeting-toggle)`; assert `appendMessage` called with `('t1', objectContaining({ role:'system', author_id:'system', body: stringContaining('Meeting ended') }))` **and** `setMeetingActive('t1', false)` called.
2. **Append fires before clear** — assert `vi.mocked(appendMessage).mock.invocationCallOrder[0] < vi.mocked(setMeetingActive).mock.invocationCallOrder[0]`.
3. **Start does NOT write a marker** — seed `meeting_active:false`; click toggle (Start); assert `appendMessage` NOT called and `setMeetingActive('t1', true)` called.
4. **No-emoji guard** — the composed marker `body` arg has no `\p{Extended_Pictographic}/u`.

### `ui/src/components/sidebar/__tests__/threadApi.appendMessage.test.ts` (4) — mirror `threadApi.meeting.test.ts` (`vi.stubGlobal('fetch')`)
1. **POSTs /messages with role:system** — assert `fetch` called with `'/api/threads/t1/messages'`, `objectContaining({ method:'POST', headers:{'Content-Type':'application/json'} })`, and the serialized body parses to `{ author_id, role:'system', body, metadata }`.
2. **Returns the message dict on ok**.
3. **Returns null on `!res.ok`** (Tier-2 degrade).
4. **No-emoji guard** on the serialized body.

> **No pytest.** The `role:"system"` append uses the existing endpoint + store method unchanged; the role enum already accepts `system`. If you find yourself adding a backend method, **STOP** — re-read the verified context (you do not need one).

---

## Do NOT build (explicit non-goals)

- **NO agent raise-hand protocol.** Agents speak in facilitator order (AD-915/921); there is no agent turn-request primitive. **The who's-speaking highlight IS the turn signal** (the lit avatar = whose turn). Do not invent a raise-hand signal.
- **NO LLM-generated summary.** v1 writes a **deterministic** marker only. An LLM summary needs a backend read-thread + LLM call → forward marker.
- **NO backend change / no new store method / no `meeting_started_at` column.** Reuse `POST /api/threads/{id}/messages` (role enum already has `system`). (That is why the marker carries crew count + callsigns, not "started <t>" — start time is not persisted; see forward markers.)
- **NO `CrewVRM` change.** The highlight is a wrapper treatment on the `AvatarSlot` inner container.
- **NO audio recording / persistence**, **NO full-duplex barge-in** (AD-922 forward marker), **NO federation / multi-mesh**, **NO new config**, **NO `Glyphs.tsx` change** (the ring is CSS; the presence chip is local text), **NO change to AD-914 fan-out / AD-915 facilitator / AD-921 voice sequencer / AD-922 mic**.
- **NO immediate in-transcript echo** of the marker (the open `ProfileChatTab` message list is local state, not the store; wiring a live echo would lift state across components). The marker **persists** and appears on next thread open — that satisfies the deliverable. Live echo = forward marker.

### Forward markers (file, do not build)
- **AD-923-1** — LLM-generated meeting summary on End (small backend endpoint reads thread messages + summarizes).
- **AD-923-2** — persist `meeting_started_at` so the marker can carry start time + duration.
- **AD-923-3** — immediate in-transcript echo of the end marker (lift `ProfileChatTab` message state or add a store-backed system-message channel).
- Agent raise-hand / explicit turn-request (would need a facilitator signal); full-duplex barge-in over speaking agents (AD-922 deferred).

---

## Acceptance criteria

- [ ] `MeetingView` accepts optional `speakingAgentId`; the matching slot lights (amber ring + `meetingSpeakingPulse`), others dim, idle is neutral — **wrapper treatment, `CrewVRM` untouched**.
- [ ] `MeetingView` renders a `meeting-presence` header (crew count) + `captain-present` chip; join/leave still reflected by the existing gallery.
- [ ] `GroupChatHeader` on **End** appends a deterministic `role:'system'` marker via `appendMessage` **before** clearing `meeting_active`; Start does not; a failed append does not block End.
- [ ] `threadApi.appendMessage` POSTs `/api/threads/{id}/messages` and honest-degrades to `null`.
- [ ] `ProfileChatTab:826` passes `speakingAgentId` to `MeetingView` (one line).
- [ ] **No backend change, no pytest.** Existing pytest suite untouched and green.
- [ ] Vitest: 3 new files, **+14** floor; full UI suite green (`cd ui && npx vitest run`); `npm run build` (tsc -b + vite) green.
- [ ] HXI: motion=state pulse, amber active palette, inline SVG/CSS, **no emoji** (guard in each new test file).
- [ ] Trackers updated: roadmap AD-923 row → SHIPPED; `PROGRESS.md` block; `DECISIONS.md` AD-923 entry; **epic-complete note**.
- [ ] Stage only the explicit changed paths (NOT `git add -A`); run a deletion audit before commit. Do NOT push.
- [ ] **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Epic complete

AD-923 is the **last AD of the "Ad-hoc Crew Collaboration (group chat → meeting)" epic (AD-913 → AD-923)**. After this commit:
- **Phase 1 (text):** participant management, group fan-out, turn-taking facilitator, file sharing, UI group-chat, agent-initiated chats, visibility + join (AD-913 → AD-919).
- **Phase 2 (meeting voice + avatars):** meeting mode + avatar gallery, sequenced meeting voice, Captain voice input, **presence + speaking indicator + transcript writeback** (AD-920 → AD-923).

The Captain can now create/join a group chat, promote it to a live meeting, see/hear the crew speak in turn with the speaker lit, talk back by voice, and end the meeting with a transcript marker written back to the thread. **Close the epic in `PROGRESS.md`** (note Phase 1 + Phase 2 complete) and record the forward markers above for any future meeting work (LLM summary, start-time persistence, live echo, raise-hand, barge-in).
