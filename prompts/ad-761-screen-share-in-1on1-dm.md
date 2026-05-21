# AD-761 — Screen share in 1:1 agent DM (ProfileChatTab + WardRoom parity)

Status: drafted
Issue: #707
Depends on: AD-744 (`captureScreenShareFrame`), AD-733-2 (`useScreenStream`), AD-720 (AttachmentStore)

## Captain bug report (2026-05-20)

There is no way to start a screen-share session with an agent from the 1:1 chat experience. The Captain expected this to be available.

## Root cause

Two screen primitives shipped in prior waves but neither is exposed in `ProfileChatTab.tsx` (the 1:1 agent DM panel):

1. **AD-744** `captureScreenShareFrame` (`ui/src/hooks/useScreenShare.ts`) — one-shot capture: prompts `getDisplayMedia`, grabs a single frame, stops the track, posts it to the agent. Wired today only in `ui/src/components/wardroom/WardRoomThreadDetail.tsx`.
2. **AD-733-2** `useScreenStream` (`ui/src/hooks/useScreenStream.ts`) — ambient long-lived stream with per-frame sampling at configurable FPS. Wired today only in `ui/src/components/settings/sections/PerceptionLivePanel.tsx`.

The 1:1 DM never got a screen-share button on either model. The Captain has no surface to initiate either flow from inside an agent conversation.

## Scope (v1)

### 1. One-shot "Share screen" button in `ProfileChatTab.tsx`
- Add a screen-share icon button next to the existing mic / attach buttons in the input toolbar.
- Click → `captureScreenShareFrame({ agentId })`.
- The hook already (per AD-744): prompts `getDisplayMedia`, grabs one frame, stops the track, uploads to `AttachmentStore`, returns an attachment id. Append it to `pendingAttachments` exactly the way the file picker does today, so the next message send includes the screenshot.
- Visual feedback: button pulses amber while capture is in flight; on success the attachment chip appears in the existing chip row; on failure surface the error in the existing `attachError` slot.
- Icon: stroke-based SVG (monitor + arrow). No emoji (HXI Design Principle #3).

### 2. Live "Share screen with agent" toggle (ambient mode)
- Right-click the screen-share button (parity with AD-760 mic UX) opens a small popover:
  - **Capture once** (default, the AD-744 path above)
  - **Live screen share** (AD-733-2 ambient path with this agent as the audience)
- Selecting **Live screen share** calls `startScreenStream({ fps: 1 })` and tags the active stream with the `agentId` so the per-frame supervisor knows where to deliver vision context.
  - The supervisor pipeline already exists for the perception path. Reuse it; do NOT branch a new ingest path.
  - When the agent DM is closed or another agent is selected, the live stream stops automatically (`stopScreenStream` in the cleanup effect).
- Persist the per-agent preference in `localStorage` under `hxi_chat_screen_mode_${agentId}` (`once` | `live`, default `once`).
- The browser-level "share screen" indicator is the authoritative privacy signal — augment it with the existing `CameraLiveIndicator` pattern so the Captain always sees that a stream is active for this agent.

### 3. Consent + safety
- The browser `getDisplayMedia` consent prompt is the floor — never bypass it.
- When live mode starts, write a single audit line via the existing journal/event log: `screen_share.started agent_id=X mode=live`. On stop, emit `screen_share.stopped agent_id=X reason=...`. Reuse whatever telemetry sink AD-733-2 already uses; do not invent a new one.
- If the user revokes the share via browser UI (`onended` on the track), the cleanup path must fire `stopScreenStream` AND clear the per-agent preference back to `once` so the next session doesn't surprise them by re-prompting.

## Out of scope (do NOT bundle into this AD)

- WebRTC peer-to-peer sharing between two human Captains (this is local-agent only).
- Multi-monitor selection UX (browser prompt covers this).
- Region-of-interest cropping or window-only sharing beyond what the browser prompt offers.
- Recording / saving the stream to disk.
- Native packaged tray app (AD-759).
- Voice/conversation changes (AD-760).

## Tests

### Vitest (ui/)
- `ProfileChatTab.screenShare.test.tsx`:
  - Click the screen-share button calls `captureScreenShareFrame` with the correct `agentId` and adds the returned attachment to `pendingAttachments`.
  - Failure path surfaces `attachError`.
  - Right-click opens menu with `Capture once` and `Live screen share` items.
  - Selecting `Live screen share` calls `startScreenStream({ fps: 1 })` and persists `hxi_chat_screen_mode_${agentId}=live`.
  - On unmount, `stopScreenStream` fires.
  - On `agentId` change, the previous live stream stops before the new one starts.
- Existing tests:
  - `useScreenShare.test.ts` and `useScreenStream.test.ts` must still pass unchanged.

### Pytest
- No backend changes expected; if any new endpoint is touched, run targeted: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -k "screen or share or perception" -p no:xdist`.

## Acceptance signals

- Captain can click "Share screen" in a 1:1 DM and the next message includes the screenshot attachment.
- Right-click on that button offers `Capture once` / `Live screen share`.
- Live mode runs the ambient stream against the active agent; closing the DM stops the stream automatically.
- Browser screen-share indicator is always live whenever a stream is active.
- `npm run build` clean.
- All existing AD-744 / AD-733-2 tests still pass.

## Forward markers

- AD-761a — parity in IntentSurface omnibus (decomposer) chat.
- AD-761b — region/window picker UI in HXI itself rather than relying on browser prompt (deferred unless real usability gap surfaces).

## Engineering principles compliance

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- Type annotations on all new public TS exports.
- No emoji in the screen-share button or popover (stroke-based SVG).
- Reuse the existing AD-733-2 ingest path; do not duplicate the supervisor wiring.
- Browser consent prompt is never bypassed.
- Audit log line on start/stop using the existing telemetry sink.
- Tests cover happy path, failure, mode switch, agent switch, unmount.
