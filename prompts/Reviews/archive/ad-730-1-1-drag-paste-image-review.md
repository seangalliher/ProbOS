# Review: AD-730-1-1 — Drag/Drop + Paste Image in WardRoomThreadDetail
**Verdict:** ✅ Approved
**Small, well-scoped UI-only addition; mirrors a verified IntentSurface pattern.**

## Required (must fix before building)

(none)

## Recommended (should fix)

1. **No single wrapper around chip strip + reply input — drop target ambiguous.** Live read of [WardRoomThreadDetail.tsx:233-269](ui/src/components/wardroom/WardRoomThreadDetail.tsx#L233-L269) shows the chip strip `<div data-testid="wardroom-dm-attachment-chips">` (~line 234) and the reply input `<div>` (~line 270) are SIBLING divs, not nested. The prompt instructs "Wire on the existing reply-form container `<div>` (the wrapper around the chip strip + textarea + buttons)" — that wrapper does not exist. Three valid fixes; the prompt should pick one explicitly:
   - (a) Wrap both divs in a new container and put `onDrop`/`onDragOver` there.
   - (b) Add the handlers to BOTH divs separately.
   - (c) Add handlers only to the reply-input div and accept that drops onto the chip strip don't register (degraded but tolerable).
   Without locking this, the Builder's choice may not match the test's drop-target assertion.

2. **Test #3 negative assertion is JSDOM-fragile.** "Assert `event.preventDefault()` NOT invoked" on a synthetic `ClipboardEvent` requires either spying on the prototype or constructing a custom event with a tracked `preventDefault`. Cleaner functional assertion: spy on `fetch` (or extract `uploadAttachment` to a mockable helper) and assert it was NOT called when the clipboard contains only `text/plain`. Same coverage, fewer brittle DOM-internal assumptions.

## Nits (style/minor)

1. Pasted-file naming: `pasted-${Date.now()}.${blob.type.split('/')[1] || 'png'}` would yield `pasted-N.svg+xml` for `image/svg+xml`. Browser clipboard images are nearly always `image/png` so this is theoretical, but consider a small map (`png|jpeg|webp|gif → that ext, else 'png'`).
2. `for (const file of files) { await uploadAttachment(file); }` uploads sequentially. AD-720d-1 in the same wave warns when image count > 5; sequential N×latency on a multi-file drop is operator-noticeable. Could `Promise.all(files.map(uploadAttachment))` — purely a polish concern, not blocking. Forward-marker territory.
3. `accept={ALLOWED_ATTACHMENT_MIMES.join(',')}` on the file input enforces MIME on the picker path; drag/drop bypasses that filter (the OS gives whatever the user dropped). Server-side check at `/api/chat/attachments/multipart` is the actual enforcement (prompt notes this) — but consider a one-line client-side guard inside `handleDrop` for fast feedback (`if (!ALLOWED_ATTACHMENT_MIMES.includes(file.type)) { setAttachError(...); continue; }`). Optional polish.

## Verified (looks good)

- `async function uploadAttachment(file: File): Promise<void>` at [WardRoomThreadDetail.tsx:143](ui/src/components/wardroom/WardRoomThreadDetail.tsx#L143) — confirmed; reuses existing helper, no new server-side surface.
- `pendingAttachments` / `setPendingAttachments` / `removePendingAttachment` all present.
- `attachment_ids: pendingAttachments.map(a => a.attachment_id)` at line 111 — DM branch wiring intact.
- `handlePaste` precedent in [IntentSurface.tsx:448](ui/src/components/IntentSurface.tsx#L448) — verified, the prompt's pattern correctly mirrors it.
- `wardRoomThreadDetail: { thread: FAKE_THREAD as any, posts: [] }` fixture in `WardRoomDmSync.test.tsx:29` — confirmed test fixture pattern available.
- `MAX_ATTACHMENT_BYTES` / `ALLOWED_ATTACHMENT_MIMES` in scope at top of file — uploadAttachment's existing guards apply uniformly to drag/paste paths.
- HXI Design Principles compliance: zero new icons (#3 satisfied); paste/drop is additive ergonomic input — no motion/visual change required (#4 N/A); no emoji introduced.
- Cross-prompt audit: this prompt touches only `ui/`. No collision with AD-724 / AD-720d-1 / AD-719-718 file sets.
- Phase ordering: UI-only; no Python startup interaction.


### Re-review (pass-2): unchanged from pass-1, verdict re-affirmed ✅

