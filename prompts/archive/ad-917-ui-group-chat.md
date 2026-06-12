# AD-917 — UI group-chat experience (in-chat group controls)

**Status:** Ready to build
**Dependencies:** AD-913 (`POST/DELETE /api/threads/{id}/participants`), AD-914 (group fan-out on `POST /api/threads/{id}/messages`), AD-916 (`attachment_ids` on the message append) — all SHIPPED + committed.
**Estimated tests:** +18 Vitest (floor; ~22 named) across 4 new test files.
**Target repo:** OSS (`d:\ProbOS`). **No new backend** — this AD drives existing endpoints only.

One-line: Give the Captain the in-chat group controls — **rename the room**, **add a participant** (@-picker), **see participant avatars**, and **attach/drop a file** — layered over the AD-913/914/916 thread endpoints, with the Captain's send routing to the group fan-out path once a thread has ≥2 crew participants.

---

## Problem

The 1:1 chat ([ui/src/components/profile/ProfileChatTab.tsx](../ui/src/components/profile/ProfileChatTab.tsx)) posts a Captain turn to the **single-agent** endpoint `POST /api/agent/{id}/chat` (ProfileChatTab.tsx:593), with `attachment_ids` already wired (ProfileChatTab.tsx:590) and an HXI-compliant inline-SVG paperclip attach button already present (ProfileChatTab.tsx:826-857). It hydrates the client `chatThreads` map from the response `thread_id`/`title` (ProfileChatTab.tsx:605-625).

The group backend is fully shipped but **unreachable from this UI**:

- AD-914 group fan-out fires **only** on `POST /api/threads/{id}/messages` when `body.role == "captain"` AND there are ≥2 crew-agent participants (threads.py:280-292). It returns `{**msg.to_dict(), "per_agent_replies": [...]}`, where each reply is `{"agent_id", "callsign", "text"}` (thread_fanout.py `group_chat_fanout` docstring/return). The 1:1 `/api/agent/{id}/chat` path the UI currently uses will **never** fan out.
- AD-913 participant endpoints exist (`POST /api/threads/{id}/participants` body `{agent_id}` → updated `thread.to_dict()`, threads.py:302-315; `DELETE /api/threads/{id}/participants/{agent_id}` → updated `thread.to_dict()`, threads.py:318-329) but have **no client wrapper** — [ui/src/components/sidebar/threadApi.ts](../ui/src/components/sidebar/threadApi.ts) has `patchThread` (title/title_locked) and `createThread`/`deleteThread`, but nothing for participants.
- The rename affordance has a backend (`PATCH /api/threads/{id}` with `title` + `title_locked`, `UpdateThreadRequest` threads.py:46-62) and a client wrapper (`patchThread`), but **no UI control**.
- There is no participant avatar strip and no add-participant UI in the chat.

There is no group-chat surface. AD-917 builds the in-chat controls and the one send-routing branch needed to make them functional.

---

## Solution overview

Build **focused, independently-testable new components** + **threadApi participant wrappers** + **one new glyph** + a **minimal ProfileChatTab edit** (mount the header; branch the send). Do **not** extend the embedded AD-719 picker, and do **not** touch the Ward Room.

```
ui/src/components/icons/Glyphs.tsx          (EDIT)  + UserPlus glyph (HXI inline SVG)
ui/src/components/sidebar/threadApi.ts       (EDIT)  + addParticipant / removeParticipant
ui/src/components/profile/AddParticipantPopover.tsx  (NEW)  @-style crew popover (reuses `agents` store + AgentAvatarBadge)
ui/src/components/profile/GroupChatHeader.tsx        (NEW)  rename + participant avatar strip + add-participant
ui/src/components/profile/ProfileChatTab.tsx (EDIT, minimal)  mount <GroupChatHeader>; group send-routing branch
```

### Why new components (not extend ProfileChatTab / extract the AD-719 picker)

- **ProfileChatTab is hard to render in tests** — its existing tests use a minimal wrapper because it "has heavy store dependencies" (ProfileChatTab.bf294b.test.tsx:1-7). Putting the group controls in **new** components keeps them directly renderable and testable.
- **The AD-719 "@-picker" is not a component.** It is ~120 lines of inline state + handlers + a portal'd popover embedded in [ui/src/components/IntentSurface.tsx](../ui/src/components/IntentSurface.tsx) (`crewRows` IntentSurface.tsx:487, `pickerMatches` :508, `handleInputChange`/`confirmPickerSelection`/`removeMention` :512-563, AD-719c keyboard state machine :420/:453), bound to **caret position and `@`-in-textarea** semantics. The add-participant flow is a different interaction shape (button → popover → select → POST), and IntentSurface is the app's most heavily-tested input. **Reuse the right atom**: the data source (`useStore((s) => s.agents)`, IntentSurface.tsx:67, filtered `isCrew && callsign`) + `AgentAvatarBadge` + the keyboard-nav pattern. **Do NOT refactor IntentSurface.**

---

## Section 1 — `UserPlus` glyph (Glyphs.tsx, EDIT)

`Glyphs.tsx` has `ChevronDown/Up/Right`, `Arrow*`, `Close`, `Undock`/`Dock`, `Status*`, etc., all built on a shared `defaultProps` (`strokeWidth: 1.5`, `strokeLinecap/Join: 'round'`, `stroke: 'currentColor'`, Glyphs.tsx:3-10). There is **no** person/user/plus glyph. Add one (HXI Principle #3 — stroke-SVG, no emoji, no fill):

```tsx
// AD-917: add-participant affordance for the group-chat header (HXI #3 — stroke-SVG, no fill).
export const UserPlus: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <circle cx="6" cy="5" r="2.5" />
    <path d="M2 13 a4 4 0 0 1 8 0" />
    <path d="M12 5 V9 M10 7 H14" />
  </svg>
);
```

(Optional, only if a rename icon is wanted instead of click-to-edit: a `Pencil` glyph may be added the same way. Not required — see Section 3.)

---

## Section 2 — `threadApi` participant wrappers (threadApi.ts, EDIT)

Add to [ui/src/components/sidebar/threadApi.ts](../ui/src/components/sidebar/threadApi.ts) (alongside `patchThread`/`deleteThread`), honest-degrading to `null`/`false` like the existing wrappers (Tier-2). Endpoints verified at threads.py:302 (POST) and threads.py:318 (DELETE); both return the updated `thread.to_dict()`.

```ts
/**
 * AD-917: add a crew agent to a thread.
 * POST /api/threads/{id}/participants  body {agent_id}  -> updated thread.to_dict()
 * (404 if thread missing, 400 if agent_id empty — both honest-degrade to null.)
 */
export async function addParticipant(
  threadId: string, agentId: string,
): Promise<AD791aChatThreadView | null> {
  try {
    const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}/participants`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: agentId }),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as AD791aChatThreadView;
    return data && typeof data.id === 'string' ? data : null;
  } catch {
    return null;
  }
}

/**
 * AD-917: remove a participant.
 * DELETE /api/threads/{id}/participants/{agent_id}  -> updated thread.to_dict()
 */
export async function removeParticipant(
  threadId: string, agentId: string,
): Promise<AD791aChatThreadView | null> {
  try {
    const res = await fetch(
      `/api/threads/${encodeURIComponent(threadId)}/participants/${encodeURIComponent(agentId)}`,
      { method: 'DELETE' },
    );
    if (!res.ok) return null;
    const data = (await res.json()) as AD791aChatThreadView;
    return data && typeof data.id === 'string' ? data : null;
  } catch {
    return null;
  }
}
```

---

## Section 3 — `AddParticipantPopover.tsx` (NEW)

A focused, keyboard-navigable crew picker. Reuses the **same data source** as the AD-719 picker (`useStore((s) => s.agents)`) and `AgentAvatarBadge` for each row. **No IntentSurface coupling.**

**Props:**
```ts
interface AddParticipantPopoverProps {
  existingParticipantIds: string[];   // exclude agents already in the thread
  onAdd: (agentId: string) => void;   // parent performs the POST + strip update
  onClose: () => void;
}
```

**Behavior:**
- Derive crew rows from `agents`: keep `a.isCrew && a.callsign`, **exclude** ids in `existingParticipantIds` and the literal `"captain"`. Dedupe by callsign. (`department` is **not** on the base `Agent` interface — access defensively: `(a as Agent & { department?: string }).department ?? ''`, mirroring IntentSurface.tsx:497.)
- A prefix `<input>` filters by `callsign`/`displayName` (case-insensitive, `startsWith`), `slice(0, 8)`.
- Keyboard: ArrowUp/ArrowDown move the highlighted row (clamp + scroll-into-view), Enter/Tab confirm the highlighted row → `onAdd(agentId)`, Esc → `onClose()`. Mouse click on a row also confirms.
- Each row: `<AgentAvatarBadge agentId callsign department size={24} />` + callsign + dim displayName. Active row: amber wash (`rgba(240,176,96,0.12)`); inactive transparent. `data-testid="add-participant-row"` per row, `data-testid="add-participant-popover"` on the container.
- HXI: amber `#f0b060` active / dim `#666680` inactive; **no emoji**.

This component does not call the API itself — the parent (`GroupChatHeader`) owns the POST + store hydrate, which keeps the popover pure and trivially testable with a mocked `agents` store.

---

## Section 4 — `GroupChatHeader.tsx` (NEW)

The in-chat group-controls bar. Mounts at the top of the chat. Reads the active thread from the store and renders: editable title, participant avatar strip, add-participant button/popover.

**Props:** `{ threadId: string }`.

**State source:** `const thread = useStore((s) => s.chatThreads.get(threadId));` and `const agents = useStore((s) => s.agents);` and `const setChatThread = useStore((s) => s.setChatThread);`. The thread view is `AD791aChatThreadView` (useStore.ts:209-224) — has `id`, `title`, `participants: string[]`.

**Title (rename):**
- Render `thread.title` as text; clicking it swaps to an `<input>` (inline edit, `data-testid="group-chat-title-input"`). Enter or blur with a changed, non-empty value → `await patchThread(threadId, { title: next, title_locked: true })` (threadApi `patchThread`; `title_locked` routes through `set_title(lock=True)` so first-turn auto-naming skips this thread, threads.py:46-62). On a non-null response, `setChatThread(updated)`. Esc cancels. (No icon required; a `Pencil` glyph hover-affordance is optional.)

**Participant avatar strip:**
- Resolve each id in `thread.participants` to its agent via `agents.get(id)`; **exclude** `"captain"` and any non-crew/unknown id. For each crew participant render `<AgentAvatarBadge agentId={id} callsign={agent.callsign} department={dept} size={24} />` (dept via the defensive cast). Container `data-testid="participant-strip"`.
- **Optional remove** (cheap — DELETE endpoint exists): on hover, a small `Close` glyph (reuse the existing `Close` from Glyphs) `data-testid="remove-participant-{id}"` → `await removeParticipant(threadId, id)` → `setChatThread(updated)` on success.

**Add-participant:**
- A `UserPlus` button (`data-testid="add-participant-button"`, `aria-label="add participant"`, amber `#f0b060`) toggles `<AddParticipantPopover>`.
- `onAdd={async (agentId) => { const updated = await addParticipant(threadId, agentId); if (updated) setChatThread(updated); setPickerOpen(false); }}` — the POST returns the updated thread (with the new participant), so the strip re-renders from `thread.participants` immediately.

**Empty/cold-start:** if `thread` is undefined (no thread yet), render nothing. Rename + add-participant appear once a thread exists; adding the 2nd crew participant is what turns a 1:1 into a group (see Section 5).

HXI: inline-SVG glyphs only, amber/dim palette, **no emoji**.

---

## Section 5 — ProfileChatTab edits (minimal)

Two edits. **Do not** restructure the file or touch the voice/screen-share/artifact code.

**5a. Mount the header.** The render returns at ProfileChatTab.tsx:734; the message list maps at :747. Compute the active thread id the same way the send path does (`threadId ?? threadIdByAgent.get(agentId)`) and mount the header as the first child of the outer container:

```tsx
// AD-917: in-chat group controls (rename / participants / add). Renders
// nothing until a thread exists. Mounted above the message list.
{activeThreadId && <GroupChatHeader threadId={activeThreadId} />}
```

**5b. Branch the send to the group fan-out path.** In `sendText` (the existing body around ProfileChatTab.tsx:575-649), after computing `attachmentIds`, determine whether the active thread is a group and route accordingly. A thread is a **group** when its crew participants ≥2 — resolve from the store: `crewParticipantCount = thread.participants.filter(id => id !== 'captain' && agents.get(id)?.isCrew).length` (read `chatThreads.get(activeThreadId)` and `s.agents`).

- **Group (≥2 crew):** `POST /api/threads/{activeThreadId}/messages` with body `{ author_id: 'captain', role: 'captain', body: text || '(attachment)', attachment_ids: attachmentIds }`. (`role`/`author_id` convention verified in test_ad914_group_chat_fanout.py:138; `body` has `min_length=1` so the `'(attachment)'` placeholder is required for attach-only sends, threads.py:67.) On the response, render each `data.per_agent_replies[]` (`{agent_id, callsign, text}`) as an agent message via the existing `addAgentMessage(agentId, 'agent', text)` store action (best-effort; attribution by callsign prefix is acceptable for v1). The Captain message is already shown locally via the existing `addAgentMessage(agentId, 'user', displayText)` call.
- **1:1 (default):** the existing `POST /api/agent/${agentId}/chat` path (ProfileChatTab.tsx:593) is preserved **byte-identical**, including the `thread_id`/`title` hydrate.

Keep the branch small and self-contained; the 1:1 path must be unchanged when the thread is not a group.

---

## Tests (Vitest — the UI hard rule)

Run with `cd ui && npx vitest run`. Co-locate per the existing convention (`ui/src/components/**/__tests__/`). Floor **+18**; named below (~22). Every component test includes a **no-emoji guard** (regex over rendered HTML, e.g. `expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u)`).

### `ui/src/components/sidebar/__tests__/threadApi.participants.test.ts` (NEW, ~5)
1. `addParticipant` POSTs to `/api/threads/{id}/participants` with JSON body `{agent_id}` and returns the parsed thread.
2. `addParticipant` returns `null` on `!res.ok`.
3. `addParticipant` returns `null` on fetch throw (honest-degrade).
4. `removeParticipant` DELETEs `/api/threads/{id}/participants/{agentId}` (ids URL-encoded) and returns the parsed thread.
5. `removeParticipant` returns `null` on `!res.ok`.

### `ui/src/components/profile/__tests__/AddParticipantPopover.test.tsx` (NEW, ~6)
1. Renders one row per crew agent from a mocked `agents` store; **excludes** ids in `existingParticipantIds` and `"captain"`.
2. Prefix input filters rows by callsign (case-insensitive `startsWith`).
3. ArrowDown/ArrowUp move the highlighted row; Enter calls `onAdd` with the highlighted agent id.
4. Mouse click on a row calls `onAdd` with that id.
5. Esc calls `onClose`.
6. No-emoji guard.

### `ui/src/components/profile/__tests__/GroupChatHeader.test.tsx` (NEW, ~7)
1. Participant strip renders an `AgentAvatarBadge` (`data-testid="agent-avatar-badge"`) for each **crew** participant in `thread.participants`, excluding `"captain"`.
2. Clicking the title shows the edit input; submitting a changed value calls `patchThread(threadId, { title, title_locked: true })` (mock threadApi) and calls `setChatThread` with the response.
3. Empty title submit is a no-op (no PATCH).
4. Add-participant button opens the popover; selecting an agent calls `addParticipant(threadId, agentId)` (mock) and the strip updates from the returned thread.
5. (Optional remove) clicking remove-× calls `removeParticipant(threadId, agentId)` and updates the strip.
6. Renders nothing when `thread` is undefined.
7. No-emoji guard.

### `ui/src/components/profile/__tests__/ProfileChatTab.groupsend.test.tsx` (NEW, ~4)
Use the established minimal-wrapper + `vi.fn()` fetch-mock pattern (mirror ProfileChatTab.bf294b.test.tsx). Extract or replicate the send-routing decision so it is testable without rendering the full ProfileChatTab.
1. When the active thread has ≥2 crew participants, a Captain send issues `POST /api/threads/{id}/messages` (NOT `/api/agent/{id}/chat`).
2. The group POST body includes `attachment_ids` when a file is attached.
3. Attach-only group send uses the non-empty `'(attachment)'` body placeholder.
4. A 1:1 thread (≤1 crew) still posts to `/api/agent/{id}/chat`.

**Maps to the 5 required tests:** rename→PATCH (GroupChatHeader #2); add-participant→POST participants + strip update (GroupChatHeader #4 + AddParticipantPopover #3/4); attach includes `attachment_ids` (ProfileChatTab.groupsend #2); strip renders avatars from `thread.participants` (GroupChatHeader #1); no-emoji guard (all four files).

---

## HXI compliance (state explicitly)

- All icons are **inline SVG** from `Glyphs.tsx` (`UserPlus` new; `Close` reused), `strokeWidth: 1.5`, `strokeLinecap: 'round'`, no fill. **No emoji** anywhere in the new UI (enforced by the no-emoji guard in every component test).
- Palette: active amber `#f0b060`, inactive dim `#666680`; participant avatars use the existing `AgentAvatarBadge` `DEPT_COLORS` (AgentAvatarBadge.tsx:10-16). Amber washes (`rgba(240,176,96,0.12)`) match the existing chat affordances.
- Motion/glow encodes state only (HXI #4): hover-reveal for remove-×, amber highlight for the active picker row.

---

## What this does NOT change (Do NOT build)

- **No new backend / no router edits.** AD-913/914/916 endpoints are used as-is.
- **No meeting / voice / 3D avatar gallery** (AD-920+). Text group chat only.
- **No agent-initiated chat creation** (`create_group_chat` intent) — that is AD-918.
- **No left-rail group-chat visibility list / Join button** — that is AD-919.
- **Do NOT touch `IntentSurface.tsx`** or its AD-719/719c picker. Do not extract or refactor it.
- **Do NOT touch the Ward Room** (`ui/src/components/wardroom/*`). The chat attach surface is ProfileChatTab's own existing uploader (`/api/chat/attachments/multipart`), not the Ward Room's.
- **Do NOT change the 1:1 `/api/agent/{id}/chat` send path** except to add the group branch around it.
- No new store slice — reuse `chatThreads`, `setChatThread`, `agents`, `threadIdByAgent`, `addAgentMessage`.

---

## Tracking

- Flip the AD-917 row in [docs/development/roadmap.md](../docs/development/roadmap.md) (line 367) to `SHIPPED <date> gate-verified` on green.
- Update PROGRESS.md test count.
- No `DECISIONS.md` entry required (UI wiring over shipped endpoints; no new architectural decision).

---

## Acceptance criteria

1. `UserPlus` glyph added to `Glyphs.tsx` (HXI inline SVG, `strokeWidth 1.5`, no fill).
2. `addParticipant`/`removeParticipant` added to `threadApi.ts`, honest-degrading to `null`.
3. `AddParticipantPopover.tsx` and `GroupChatHeader.tsx` created, reusing `useStore((s) => s.agents)` + `AgentAvatarBadge` + `threadApi`; **no IntentSurface / Ward Room imports**.
4. `ProfileChatTab.tsx` mounts `<GroupChatHeader>` and routes Captain sends to `POST /api/threads/{id}/messages` when the active thread has ≥2 crew participants, including `attachment_ids`; the 1:1 path is byte-identical otherwise.
5. ≥18 new Vitest tests across the 4 named files, all green: `cd ui && npx vitest run`. The full existing UI suite stays green.
6. Every new component test includes a no-emoji guard.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-06-07)

```
ui/src/components/profile/ProfileChatTab.tsx
  :590  attachment_ids: attachmentIds,                       (1:1 send already passes attachment_ids)
  :593  const res = await fetch(`/api/agent/${agentId}/chat`,(1:1 endpoint — NOT the thread messages path)
  :605-625 setThreadForAgent / setChatThread hydrate from response thread_id/title
  :675  fetch('/api/chat/attachments/multipart', ...)        (own uploader — not the Ward Room)
  :826-857 inline-SVG paperclip attach button, aria-label="attach file" (HXI-compliant, no emoji)
  :734  return ( ...                                          (render root — header mounts here)
  :747  messages.map(msg => ( ...                             (per-agentId conversation render)

src/probos/routers/threads.py
  :46-62  UpdateThreadRequest { title, ..., title_locked }   (PATCH backs the rename)
  :64-73  AppendMessageRequest { author_id, role ^(captain|agent|system)$, body min_length=1, metadata, attachment_ids }
  :75-80  ParticipantRequest { agent_id: str = "" }
  :215    @router.post("/{thread_id}/messages")
  :280-292 AD-914 gate: role=="captain" AND >=2 crew -> returns {**msg.to_dict(), "per_agent_replies": [...]}
  :302-315 @router.post("/{thread_id}/participants") add_participant -> thread.to_dict() (400 empty / 404 missing)
  :318-329 @router.delete("/{thread_id}/participants/{agent_id}") remove_participant -> thread.to_dict()

src/probos/routers/thread_fanout.py
  group_chat_fanout(...) -> list[{"agent_id","callsign","text"}]   (per_agent_replies entry shape)
  crew_agent_participants(...) excludes Captain/non-crew

tests/test_ad914_group_chat_fanout.py
  :138  store.append_message(t.id, author_id="captain", role="captain", body="status?")  (captain convention)

ui/src/components/sidebar/threadApi.ts
  patchThread(threadId, {title?, title_locked?}) exists; createThread/deleteThread exist; NO participant wrappers

ui/src/store/useStore.ts
  :209-224 interface AD791aChatThreadView { id; title; participants: string[]; ... }
  :468 / :1249 setChatThread action
ui/src/components/IntentSurface.tsx
  :67   const agentsMap = useStore((s) => s.agents);          (the crew data source to reuse)
  :487  crewRows = agents filtered isCrew && callsign; :508 pickerMatches; :420/:453 AD-719c keyboard (INLINE — not a component)
  :497  (a as Agent & { department?: string }).department    (department is a cast, not on base Agent)

ui/src/components/AgentAvatarBadge.tsx
  :26   props { agentId, callsign, department?, size? }; :44 data-testid="agent-avatar-badge"; :10-16 DEPT_COLORS

ui/src/components/icons/Glyphs.tsx
  :3-10 shared defaultProps strokeWidth 1.5 / strokeLinecap round / stroke currentColor; exports Chevron*/Arrow*/Close/Undock/Dock/Status*  (NO UserPlus/Person/Plus)

ui/src/components/profile/__tests__/ProfileChatTab.bf294b.test.tsx
  :1-7  established "minimal wrapper, mock the store" test pattern (ProfileChatTab too heavy to render whole)
```
