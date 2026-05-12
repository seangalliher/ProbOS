# AD-730-1 — WardRoom DM attach button (Wave 154)

**GH:** [#631](https://github.com/seangalliher/ProbOS/issues/631). **Status:** Buildable.

## Problem

WardRoom DM thread reply composer (`ui/src/components/wardroom/WardRoomThreadDetail.tsx`) sends via `/api/agent/{id}/chat` — which already supports `attachment_ids` after AD-730. The UI just doesn't have the attach button. Captain can attach in the main composer (IntentSurface) and the per-agent profile chat (ProfileChatTab); WardRoom is the gap.

## Scope

1. Mirror the **paperclip + chip-strip + file-picker** pattern from `ui/src/components/profile/ProfileChatTab.tsx` (canonical reference — same `/api/agent/{id}/chat` endpoint). Specifically:
   - `pendingAttachments` state (`useState<ChatAttachment[]>([])`).
   - `uploadAttachment(file)` helper that POSTs to `/api/chat/attachments/multipart` (same endpoint as ProfileChatTab line ~148).
   - Hidden `<input type="file" />` triggered by a paperclip button next to the textarea.
   - Chip strip above the textarea showing pending attachments with × removal.
   - Reset `pendingAttachments` to `[]` after successful send (mirroring ProfileChatTab line 106).
   - On `submitReply`, include `attachment_ids: pendingAttachments.map(a => a.attachment_id)` in the `/api/agent/{id}/chat` body.
2. **Only** the file-picker path in v1. **Out of scope for v1:** drag-and-drop, paste-image, multi-select beyond what the picker already supports. File AD-730-1.1 forward marker at wave close for drag-drop/paste.
3. Apply only to the DM branch (`isDm && targetAgentId`). The async fallback path (non-DM threads or no resolved target) does NOT attach — paperclip button hidden / disabled when `!isDm || !targetAgentId`.
4. UI styling matches existing reply composer (12px Inter, `#e0dcd4` text, `rgba(255,255,255,0.04)` background).

## Files

- `ui/src/components/wardroom/WardRoomThreadDetail.tsx` (modified).
- `ui/src/__tests__/WardRoomThreadDetail.attach.test.tsx` (new, 3 Vitest tests).

## Tests (≥3 Vitest)

1. `test_paperclip_button_hidden_in_non_dm_view` — render with `view='channels'` or no `targetAgentId`; assert paperclip is not in the DOM.
2. `test_paperclip_button_visible_in_dm_view` — render with `view='dm-detail'` + resolved `targetAgentId`; assert paperclip button is in DOM.
3. `test_pending_attachment_included_in_chat_post` — render DM view; mock `fetch`; simulate file picker → `/api/chat/attachments/multipart` returns `{attachment_id: "abc123", ...}`; submit; assert the `/api/agent/{id}/chat` fetch body includes `attachment_ids: ["abc123"]`.

Test runner: `cd ui && npx vitest run`.

## Out of scope (FORWARD MARKER)

- **AD-730-1.1: Drag-and-drop + paste-image in WardRoomThreadDetail.** v1 ships file-picker only. File at wave close.

## Acceptance

- Vitest passes for the new file: `cd d:/ProbOS/ui; npx vitest run src/__tests__/WardRoomThreadDetail.attach.test.tsx`.
- No regressions in existing Vitest tests (`cd ui; npx vitest run`).
- HXI Design Principle #3 — no emoji in the paperclip (inline SVG, `strokeWidth: 1.5`, matching ProfileChatTab's existing paperclip SVG byte-for-byte).
- HXI Design Principle #4 — paperclip lights amber on hover (`#f0b060`), dim default (`#666680`).
- AD-734 pre-commit hook does NOT fire (no vision-backend file staged).
- DECISIONS.md AD-730-1 entry promoted from forward marker → shipped.

## Commit

`AD-730-1: WardRoom DM attach button (Wave 154). Closes #631.`
