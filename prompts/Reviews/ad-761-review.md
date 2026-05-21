# Review: AD-761 — Screen share in 1:1 agent DM
**Verdict:** ✅ Approved
**The two screen-share primitives exist and the ProfileChatTab integration shape is sound.**

## Required (must fix before building)
*(none)*

## Recommended
1. Telemetry sink claim: prompt says "Reuse whatever telemetry sink AD-733-2 already uses." Verify-grep shows `useScreenStream.ts` does NOT call any backend telemetry endpoint — it only manages a client-side store. The audit-line claim (`screen_share.started agent_id=X mode=live`) currently has no concrete sink. Recommend the Builder pick one of: (a) post to `/api/events` with the existing event-log schema, or (b) drop the audit-line scope entirely and add `AD-761c — screen-share audit log` as a forward marker.
2. `pendingAttachments` shape verified in `ProfileChatTab.tsx:24` as `ChatAttachment[]`. `captureScreenShareFrame` returns shape needs to match `ChatAttachment` for the "append to pendingAttachments" plan to hold. Builder must confirm the hook's return shape conforms; if not, add a small adapter in the click handler.

## Nits
- Right-click menu (popover) UX: matching "AD-760 mic UX" is fine; just ensure popover dismisses on Esc + outside-click for accessibility.

## Verified
- `captureScreenShareFrame` exported from `ui/src/hooks/useScreenShare.ts:73`. ✓
- `startScreenStream`, `stopScreenStream` exported from `ui/src/hooks/useScreenStream.ts:107, 158`. ✓
- `ProfileChatTab.tsx` exists with `pendingAttachments`, `attachError`, file-picker pattern that the click handler can mirror. ✓
- `WardRoomThreadDetail.tsx` is the existing consumer of `captureScreenShareFrame` (AD-744 reference verified via `WardRoomThreadDetail.shareScreen.test.tsx:11`). ✓
- `PerceptionLivePanel.tsx` is the existing consumer of `useScreenStream` (via `ui/src/components/settings/sections/PerceptionLivePanel.tsx`). ✓
## Re-review (2026-05-20)
No revisions required. Recommended items left for Builder discretion. **Ready for GATE 1.**
