# AD-730-1-1 — Drag/Drop + Paste Image in WardRoomThreadDetail

**AD:** AD-730-1-1 (child of shipped AD-730-1).
**GH issues closed:** [#646](https://github.com/seangalliher/ProbOS/issues/646). **Pre-flight:** close [#647](https://github.com/seangalliher/ProbOS/issues/647) as duplicate of #646 BEFORE the wave starts.
**Parent AD:** AD-730-1 (WardRoomThreadDetail file-picker; shipped Wave 154 commit `2413bf6d`).
**Wave:** 154. **Estimated tests:** +3 Vitest. **Estimated wall-time:** ~1h.

---

## Solution Overview

`WardRoomThreadDetail.tsx` already has the file-picker path (`AD-730-1`, lines 9–16, 54–57, 142–183). It is missing two ergonomic input modes that the IntentSurface chat input has had since AD-720 / AD-720a:

- **Paste** (`onPaste` on the textarea) — clipboard image → upload → chip strip.
- **Drag/drop** (`onDragOver` + `onDrop` on the reply container) — file → upload → chip strip.

Both reuse the existing `uploadAttachment(file: File)` helper inside `WardRoomThreadDetail` (lines 142–164). No new server-side work — `/api/chat/attachments/multipart` already accepts the upload and `pendingAttachments` already wires through to `attachment_ids` on the DM POST.

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `ui/src/components/wardroom/WardRoomThreadDetail.tsx` | imports, ~140–185 (handlers), ~210–260 (textarea wrapper) | Add `handlePaste` + `handleDrop`/`handleDragOver`; wire to textarea + reply container. |
| `ui/src/__tests__/WardRoomThreadDetail.attach.test.tsx` | NEW | 3 Vitest boundary tests. |

No backend changes. No store changes. No type changes (`ChatAttachment` already in `store/types.ts`).

---

## Section 1 — Paste handler

In `WardRoomThreadDetail.tsx`, after `removePendingAttachment` (around line 178) add:

```typescript
// AD-730-1-1: paste image from clipboard. Mirrors IntentSurface.handlePaste.
async function handlePaste(event: React.ClipboardEvent<HTMLTextAreaElement>) {
  const items = Array.from(event.clipboardData?.items ?? []);
  const imageItem = items.find(it => it.type && it.type.startsWith('image/'));
  if (!imageItem) return; // text paste — let the textarea handle it
  event.preventDefault();
  const blob = imageItem.getAsFile();
  if (!blob) return;
  // Wrap as File so uploadAttachment's MIME/size guards apply uniformly.
  const file = new File([blob], `pasted-${Date.now()}.${blob.type.split('/')[1] || 'png'}`, {
    type: blob.type,
  });
  await uploadAttachment(file);
}
```

Wire it on the textarea — locate the existing `<textarea>` element in the reply form (it already has `value={replyText}` and `onChange={...}`). Add `onPaste={handlePaste}`.

---

## Section 2 — Drag/drop handler

After `handlePaste`, add:

```typescript
// AD-730-1-1: drag/drop file upload. Targets the textarea + chip-strip
// region. We accept any file the picker accepts; the existing MIME/size
// allow-list inside uploadAttachment + the server-side check at
// /api/chat/attachments/multipart are the actual enforcement.
async function handleDrop(event: React.DragEvent<HTMLDivElement>) {
  event.preventDefault();
  const files = Array.from(event.dataTransfer?.files ?? []);
  for (const file of files) {
    await uploadAttachment(file);
  }
}

function handleDragOver(event: React.DragEvent<HTMLDivElement>) {
  // Required to allow the drop event to fire.
  event.preventDefault();
}
```

Wire on the existing reply-form container `<div>` (the wrapper around the chip strip + textarea + buttons): add `onDrop={handleDrop}` and `onDragOver={handleDragOver}`.

---

## What This Does NOT Change

- The file-picker button stays as the explicit affordance — paste/drop are additive.
- No new MIME types accepted. The existing `ALLOWED_ATTACHMENT_MIMES` constant gates everything.
- Non-DM threads (channels view) are unaffected — `pendingAttachments` is only sent on the DM branch (line 111), and that branch is untouched.
- No new visual indicator for "drop zone active" hover state in v1 (file as forward marker AD-730-1-2 if requested).
- No multi-file UI (use multi-select in the picker — already supported).

---

## Test Plan (`ui/src/__tests__/WardRoomThreadDetail.attach.test.tsx`)

Vitest. Mock `fetch` for the `/api/chat/attachments/multipart` POST. Render `<WardRoomThreadDetail />` with a fake DM thread in the Zustand store (mirror the fixture in `WardRoomDmSync.test.tsx:25-30`).

1. **`paste image triggers upload and adds chip`** — happy path. Simulate `ClipboardEvent` with `items: [{ type: 'image/png', getAsFile: () => new File([...], 'cat.png', { type: 'image/png' }) }]`. Assert `fetch` called with multipart form, assert chip with `cat.png` (or `pasted-*.png`) appears.
2. **`drop image triggers upload and adds chip`** — happy path. Fire `DragEvent('drop', { dataTransfer: { files: [file] } })`. Assert chip appears.
3. **`paste plain text passes through to textarea`** — edge. Simulate paste with only `text/plain` items. Assert `fetch` NOT called and `event.preventDefault()` NOT invoked (textarea handles the text natively).

---

## Verification commands

```powershell
cd ui
npx vitest run src/__tests__/WardRoomThreadDetail.attach.test.tsx
npx vitest run
```

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md` (HXI Design Principle #2: SVG glyphs only — this prompt adds zero icons; #4: motion communicates state — drop-hover indicator deferred).

---

## Tracker Updates

- **PROGRESS.md**: bump UI Vitest count; add bullet under Wave 154.
- **DECISIONS.md**: append `### AD-730-1-1` (one paragraph).
- **docs/development/roadmap.md**: mark #646 closed; #647 closed as dup before wave start.

---

## Verified Against Codebase (2026-05-12)

```
grep -n "AD-730-1: file-picker attachments" ui/src/components/wardroom/WardRoomThreadDetail.tsx
  9: // AD-730-1: file-picker attachments for WardRoom DM replies.
grep -n "async function uploadAttachment" ui/src/components/wardroom/WardRoomThreadDetail.tsx
  143:  async function uploadAttachment(file: File): Promise<void> {
grep -n "pendingAttachments.map" ui/src/components/wardroom/WardRoomThreadDetail.tsx
  111:          attachment_ids: pendingAttachments.map(a => a.attachment_id),
grep -n "handlePaste" ui/src/components/IntentSurface.tsx
  448:  async function handlePaste(event: React.ClipboardEvent<HTMLInputElement>) {
grep -n "wardRoomThreadDetail: { thread:" ui/src/__tests__/WardRoomDmSync.test.tsx
  29:    wardRoomThreadDetail: { thread: FAKE_THREAD as any, posts: [] },
```
