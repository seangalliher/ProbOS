# AD-939 + AD-940 — Meeting Captain slot (camera/screen/icon) + draggable CHATS panel

**Target repo:** OSS (`d:\ProbOS`). **AD-939 + AD-940** (two small, independent frontend changes, one commit).
Highest committed (after AD-938 local): `a7393d90`. **Mode:** Builder. Frontend only. Vitest + `npm run build`.
Commit local. No push.

---

## AD-939 — MeetingView: render the Captain as a video/icon slot
**Problem (Captain-reported):** in meeting mode the crew avatars didn't show, and the Captain should appear
with their camera/screen video if shared, else an icon.

**Crew avatars are already fixed by AD-938** (the gallery was empty only because the group thread wasn't
hydrated into `chatThreads` → `MeetingView`'s `if (!thread) return null` short-circuited; AD-938 hydrates it).
This AD adds the **Captain slot**. Verified vs HEAD: `MeetingView` (`ui/src/components/profile/MeetingView.tsx`)
excludes `CAPTAIN_PARTICIPANT_ID` from the gallery and shows only a text "You (Captain)" chip
(`data-testid="captain-present"`, ~L168). `AvatarSlot` already does VRM-or-`AgentAvatarBadge` for crew.

Captain stream APIs (verified):
- `getCameraStream(): MediaStream | null` — `ui/src/hooks/useCameraStream.ts:40`; `useCameraStore` has
  `active: boolean` (`ui/src/store/useCameraStore.ts`).
- `getScreenStream(): MediaStream | null` — `ui/src/hooks/useScreenStream.ts:33`; `useScreenStore` has
  `active: boolean` (`ui/src/store/useScreenStore.ts`).

**Change:** add a `CaptainSlot` component in `MeetingView.tsx` (sibling of `AvatarSlot`) and render it in the
gallery FIRST (before the crew slots), so the Captain is always present in the meeting:
```tsx
function CaptainSlot() {
  const cameraActive = useCameraStore((s) => s.active);
  const screenActive = useScreenStore((s) => s.active);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  // Prefer camera, else screen. Attach the live MediaStream to the <video>.
  useEffect(() => {
    const stream = cameraActive ? getCameraStream() : (screenActive ? getScreenStream() : null);
    const el = videoRef.current;
    if (el && stream) { el.srcObject = stream; el.play?.().catch(() => {}); }
    return () => { if (el) el.srcObject = null; };
  }, [cameraActive, screenActive]);
  const hasVideo = cameraActive || screenActive;
  return (
    <div data-testid="captain-slot" style={{ /* mirror AvatarSlot outer: column, w120 h160, gap4 */ }}>
      <div style={{ width: 112, height: 132, position: 'relative', borderRadius: 8, overflow: 'hidden',
                    background: 'rgba(255,255,255,0.04)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {hasVideo ? (
          <video data-testid="captain-video" ref={videoRef} autoPlay muted playsInline
                 style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          // Icon fallback: a stroke-SVG person glyph in an amber-tinted circle (HXI #3, no emoji).
          <div data-testid="captain-icon" style={{ width: 64, height: 64, borderRadius: '50%',
               background: 'rgba(240,176,96,0.12)', border: '1px solid rgba(240,176,96,0.4)',
               display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#f0b060"
                 strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.5-6 8-6s8 2 8 6" />
            </svg>
          </div>
        )}
      </div>
      <span style={{ color: '#f0b060', fontSize: 11, fontWeight: 600 }}>You (Captain)</span>
    </div>
  );
}
```
- Render `<CaptainSlot />` as the first child of the avatar gallery flex row (before the `crewIds.map`).
- Keep the existing presence header chip (`captain-present`) — it is the count line; the slot is the avatar.
- Imports: `useRef`, `useEffect` (already importing `useState`); `useCameraStore`, `useScreenStore`,
  `getCameraStream`, `getScreenStream`.
- HXI #3: inline SVG, amber, no emoji.

**AD-939 tests** (Vitest, floor +4) — extend/add `MeetingView.*.test.tsx` (R3F/CrewVRM/fleet-hook mocked per
the existing `MeetingView.test` precedent; real store):
1. Captain slot renders (`captain-slot`) in the gallery.
2. Camera active → `captain-video` present; `getCameraStream` mock returns a fake stream (jsdom: assert the
   `<video>` renders + `srcObject` set attempt; mock `HTMLMediaElement.prototype.play`).
3. Neither active → `captain-icon` present, no `captain-video`.
4. Crew slots still render alongside (regression: `avatar-slot-<id>` for a 2-crew thread). No-emoji guard.

---

## AD-940 — Draggable CHATS panel
**Problem (Captain-reported):** the CHATS panel can't be moved, so when a chat window opens under it the
Captain can't drag it out of the way.

Verified vs HEAD: `<ChatsPanel />` (`App.tsx:234`) is a fixed floating panel (`data-testid="chats-panel"`).
The drag pattern is established by `GamePanel.tsx` (`gamePanelPos`/`setGamePanelPos`) and `AgentProfilePanel`
(`profilePanelPos`/`setProfilePanelPos`, `useStore.ts:334/491/828/1313`): a store `{x,y}` pos + setter, an
absolutely-positioned panel at `left/top: pos`, and a header drag handle with `onMouseDown` that tracks
`mousemove`/`mouseup` and calls the setter.

**Change:**
- `useStore.ts`: add `chatsPanelPos: { x: number; y: number }` (init e.g. `{ x: 24, y: 96 }` — match the
  current on-screen position so nothing visually jumps) + `setChatsPanelPos(pos)` — mirror
  `profilePanelPos`/`setProfilePanelPos` exactly (interface decl, initial state, action).
- `ChatsPanel.tsx`: position the panel root at `position: 'absolute', left: pos.x, top: pos.y` (read
  `chatsPanelPos`); add an `onMouseDown` drag handler on the CHATS header row (`data-testid="chats-panel"`
  header, the row with the "CHATS" label + New chat + Close) that, on drag, updates `setChatsPanelPos`
  (mirror `GamePanel`'s `startDrag` — capture offset on mousedown, `document.addEventListener('mousemove'/'mouseup')`,
  clean up on mouseup). Do NOT make the New-chat / Close buttons start a drag (stopPropagation or gate on the
  handle area). The header should show `cursor: move`.

**AD-940 tests** (Vitest, floor +3):
1. `setChatsPanelPos` updates `chatsPanelPos` (store action, mirror the AgentProfilePanel test).
2. ChatsPanel root renders at `left/top` from `chatsPanelPos` (assert inline style from a seeded pos).
3. The header has a drag affordance (`cursor: move` / a `data-testid` drag handle); a mousedown+move+up
   sequence calls `setChatsPanelPos` (mock the store action or assert the resulting pos). No-emoji guard.

---

## Gates (report exact counts)
- `cd d:\ProbOS\ui; npx vitest run` (FULL suite — report pass/skip vs the AD-938 baseline 1317; zero regressions).
- `cd d:\ProbOS\ui; npm run build` (tsc -b + vite) — clean.
- No backend change → no pytest.

## Acceptance
- Meeting mode shows the Captain slot (camera/screen video if shared, else an amber person icon) alongside the
  crew avatars (which now render after AD-938). The CHATS panel can be dragged by its header to any position.
  `npm run build` clean. Engineering-Principles compliance verified.

## Do NOT (scope fence)
- AD-939: no change to `AvatarSlot`/`CrewVRM`/the fleet telemetry binding; no new camera/screen capture flow
  (reuse the existing streams read-only); no audio. AD-940: no change to the CHATS list/filter/open logic
  (AD-938), no resize (forward marker AD-940a). Neither touches the AD-933/934/935/938 data path, the
  facilitator, the Ward Room, `Glyphs.tsx`, or `IntentMessage`.
- No push. Stage explicit paths (NOT `git add -A`); deletion-audit.

## Trackers (after gates green)
- `docs/development/roadmap.md`: AD-939 + AD-940 rows, SHIPPED + 2026-06-09 + gate note.
- `PROGRESS.md`: prepend an AD-939/AD-940 block.
- `DECISIONS.md`: AD-939 entry (Captain meeting slot, camera>screen>icon, crew avatars fixed by AD-938) +
  AD-940 entry (draggable CHATS via chatsPanelPos, GamePanel pattern), forward marker AD-940a (resize).
