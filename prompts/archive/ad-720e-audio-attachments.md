# AD-720e — Audio attachments (playback) + AD-738e-2 Refs-trailer rule

**AD:** AD-720e + AD-738e-2 (folded). **GH issues closed:** [#566](https://github.com/seangalliher/ProbOS/issues/566), [#653](https://github.com/seangalliher/ProbOS/issues/653).
**Parent ADs:** AD-720 (image paste, Wave 135), AD-720a (file upload, Wave 139), AD-720d (vision pipe-through, Wave 139), AD-721b-1 (browser-captured `audio/webm` + `audio/wav` allow-list, Wave 155), AD-731 (content-addressable attachment refs, Wave 152).
**Wave:** 159. **Estimated tests:** +4 pytest + 3 vitest. **Estimated wall-time:** ~3h. **Risk:** LOW (additive — audio MIME types add to allow-list + magic-bytes table; new render branch in attachment preview).

---

## Solution Overview

ProbOS already accepts `audio/webm` and `audio/wav` attachments (AD-721b-1 Wave 155 added them for the rhubarb lip-sync capture path; see `config.py:1124-1142` + `attachments/mime.py:27-28`). But the chat UI never renders an `<audio>` player — attachments with non-image MIMEs all fall through to a generic file icon. This AD ships **playback only**: extend the allow-list with the three additional issue-specified MIMEs (`audio/mpeg`, `audio/mp4`, `audio/ogg`), register their magic-byte signatures, and teach `IntentSurface.tsx` to render an `<audio controls>` element for any attachment whose MIME starts with `audio/`. The WardRoom paste handler is also broadened to accept audio MIMEs, but the WardRoom and ProfileChatTab chip-rendering surfaces stay chip-only (scope-collapse — see Section 4).

Transcription is explicitly **out of scope** — AD-705a (whisper.cpp WASM) remains the forward marker for that.

**AD-731 invariant preserved:** audio bytes are stored content-addressably in `AttachmentStore` (SHA-256 ref). The `<audio>` element's `src` is `/api/chat/attachments/<sha>` — same URL pattern as images. NEVER inline base64 audio into the prompt.

**Folded: AD-738e-2 (Refs-trailer standing rule, GH #653).** This wave's most substantial attachment-pipeline change naturally edits `prompts/BUILDER-EXECUTION-PLAN.md` for the audio-MIME testing recipe, so the Refs-trailer standing-rule line lands in the same edit. Folded here per Wave 159 drafter discretion (Captain's instruction).

> **Note on AD-738e-2 numbering.** DECISIONS.md AD-738e-1 (Wave 158, line 2466) reserved `AD-738e-2` as a forward marker for "noise_w / sentence_silence per-emotion overrides." Issue #653 was filed AFTER that and re-used the slot for the Refs-trailer rule. The prosody-forward-marker AD-738e-2 is RENUMBERED to **AD-738e-2-prosody** (forward marker only — never built) so the Refs-trailer rule takes the canonical AD-738e-2 slot used by the GH issue and commit history. Builder MUST update DECISIONS.md AD-738e-1's "Forward markers" line accordingly.

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `src/probos/config.py` | ~1124 (`AttachmentsConfig.allowed_mime_types`) | Add `"audio/mpeg"`, `"audio/mp4"`, `"audio/ogg"` to defaults. |
| `src/probos/attachments/mime.py` | ~18 (`_SIGNATURES`) + ~32 (`_ANY_OF`) | Register magic-byte signatures for the 3 new MIMEs; extend `_ANY_OF` to include `audio/mpeg` + `audio/mp4`. |
| `ui/src/components/IntentSurface.tsx` | ~1970 (the `att.mime.startsWith('image/')` ternary) | New branch: `att.mime.startsWith('audio/')` → render `<audio controls src={att.url}>`. |
| `ui/src/components/wardroom/WardRoomThreadDetail.tsx` | ~182 (`handlePaste` MIME filter) | Extend paste MIME-check to include `audio/`. **No render extension** — chip-only rendering preserved (scope-collapse, see Section 4). |
| `prompts/BUILDER-EXECUTION-PLAN.md` | Standing Rules section | Add AD-738e-2 Refs-trailer line. |
| `tests/test_ad720e_audio_attachments.py` | NEW | 4 pytest tests (magic-byte validators + allow-list config). |
| `ui/src/__tests__/IntentSurface.audioRender.test.tsx` | NEW | 3 vitest tests. |

Live grep confirms:
- `_SIGNATURES` dict at `attachments/mime.py:18`; two audio MIMEs already registered at lines 27-28 (webm with EBML head, wav with `RIFF`+`WAVE`).
- `allowed_mime_types` default factory at `config.py:1124`; the two existing audio MIMEs are listed at lines 1136-1138.
- IntentSurface attachment render at `IntentSurface.tsx:1970` — ternary on `att.mime.startsWith('image/')`. Builder extends to include audio branch.
- WardRoomThreadDetail paste handler at line 179-200 — filters on `it.type.startsWith('image/')` at line 182; extend to `image/` OR `audio/`. ProfileChatTab.tsx has NO `handlePaste` handler (file picker only) — the allow-list extension in Section 1 covers it via the picker path.
- `att.url` resolves to `/api/chat/attachments/<sha>` per existing convention (see test fixture in `IntentSurface.imagePaste.test.tsx:34`).

---

## Section 1 — `AttachmentsConfig.allowed_mime_types` defaults

In `src/probos/config.py:1124`, locate the `default_factory=lambda: [...]` list and add three new entries after the existing audio block (lines 1136-1138):

```python
            "audio/webm",
            "audio/wav",
            # AD-720e (Wave 159): playback-only audio attachments (mpeg, m4a, ogg).
            # AttachmentStore stores bytes content-addressably (AD-731); browser
            # renders via <audio controls src=/api/chat/attachments/<sha>>.
            # Transcription is OUT OF SCOPE — AD-705a forward marker.
            "audio/mpeg",
            "audio/mp4",
            "audio/ogg",
```

No config validator changes — the existing allow-list pattern handles arbitrary MIME strings.

---

## Section 2 — Magic-byte signatures (extend existing `_ANY_OF` mechanism)

`src/probos/attachments/mime.py` already supports any-of-alternative magic-byte matching via the `_ANY_OF: frozenset[str]` at line 32, consulted by `validate_image_bytes` at line 48 (`if declared_mime in _ANY_OF: ...`). `image/gif` is the existing inhabitant (two `GIF87a` / `GIF89a` alternatives at offset 0). MP3's four sync-byte variants and MP4's three `ftyp` brands fit the same shape; `audio/ogg` has a single signature so it stays out of `_ANY_OF`.

**Edit 1 — extend `_SIGNATURES` (`mime.py:18`).** After the existing `audio/wav` entry on line 28, add:

```python
    # AD-720e (Wave 159): playback-only audio attachments. Magic bytes
    # verified against the standard file-format specs and against real
    # sample files. Multi-option signatures (MP3 sync bytes, MP4 ftyp
    # brands) use the existing _ANY_OF mechanism — see line 32 below.
    "audio/mpeg": [
        (0, b"ID3"),                # MP3 with ID3v2 tag (most common)
        (0, b"\xff\xfb"),            # MP3 frame sync (MPEG-1 Layer 3, no ID3)
        (0, b"\xff\xf3"),            # MP3 frame sync (MPEG-2 Layer 3)
        (0, b"\xff\xf2"),            # MP3 frame sync (MPEG-2.5 Layer 3)
    ],
    "audio/mp4": [
        (4, b"ftypM4A "),            # M4A (most common form)
        (4, b"ftypmp42"),            # MP4 brand mp42
        (4, b"ftypisom"),            # MP4 brand isom
    ],
    "audio/ogg": [
        (0, b"OggS"),                # Ogg container (any codec)
    ],
```

**Edit 2 — extend `_ANY_OF` frozenset (`mime.py:32`).** Replace the one-line literal:

```python
_ANY_OF: frozenset[str] = frozenset({"image/gif"})
```

with:

```python
# AD-720e (Wave 159): MP3 sync bytes (4 variants) and MP4 ftyp brands (3
# variants) are genuine any-of alternatives at the same offset. WAV stays
# out — its (RIFF, WAVE) pair are BOTH required for a valid file.
_ANY_OF: frozenset[str] = frozenset({"image/gif", "audio/mpeg", "audio/mp4"})
```

That is the entire magic-byte change. No new dict, no new matcher branch, no extension of `validate_image_bytes` logic — the existing `if declared_mime in _ANY_OF: ...` branch at line 48 already implements the right semantics.

`audio/ogg` is intentionally NOT in `_ANY_OF` — its single signature is correctly handled by the default all-required path (with `len(sigs) == 1` that path is equivalent to any-of for the trivial case).

**No Section 2a.** The prompt as drafted gated Section 2a on "the matcher needs extending" — it does not. The existing `_ANY_OF` mechanism already provides per-MIME any-of semantics.

---

## Section 3 — IntentSurface audio render

In `ui/src/components/IntentSurface.tsx:1970`, locate the ternary:

```typescript
{att.mime.startsWith('image/') ? (
  <img src={att.url} ... />
) : (
  <div ...>{/* file icon + name */}</div>
)}
```

Change to a 3-way:

```typescript
{att.mime.startsWith('image/') ? (
  <img
    src={att.url}
    alt={att.attachment_id.slice(0, 8)}
    style={{ maxWidth: 128, maxHeight: 128, display: 'block', borderRadius: 2 }}
  />
) : att.mime.startsWith('audio/') ? (
  <audio
    controls
    src={att.url}
    preload="metadata"
    style={{ maxWidth: 220, display: 'block' }}
    aria-label={`audio attachment ${att.attachment_id.slice(0, 8)}`}
  />
) : (
  <div style={{ /* existing file-icon block */ }}>
    {/* existing inline SVG file icon — HXI principle: no emoji */}
  </div>
)}
```

Preserve every line of the existing image-render and file-icon blocks; only add the middle branch.

---

## Section 4 — WardRoomThreadDetail paste filter (MIME-only; no render extension)

In `ui/src/components/wardroom/WardRoomThreadDetail.tsx:182` (`handlePaste`), change the MIME filter to accept audio too:

```typescript
const audioOrImageItem = items.find(
  it => it.type && (it.type.startsWith('image/') || it.type.startsWith('audio/')),
);
if (!audioOrImageItem) return;
// ... rest of body uses audioOrImageItem in place of imageItem
```

Update the variable name in the rest of the function (search-and-replace `imageItem` → `audioOrImageItem` within `handlePaste` only — confirmed scope: lines 179-200 per live grep).

**No render-block extension in this AD.** WardRoomThreadDetail.tsx renders attachments as filename chips only (line 275-286: `{pendingAttachments.map(...)}` → `<span>{a.filename || a.attachment_id.slice(0, 12)}</span>`). There is NO existing `<img src=...>` block for posted-message attachments to mirror. The chip rendering surface stays unchanged; pasted audio uploads succeed and surface as a chip, identical to a pasted image's chip — playback is delivered through the IntentSurface render seam (Section 3), which is the canonical input surface in HXI design.

**Scope decision (Recommended scope-collapse applied):** audio playback renders only in IntentSurface. WardRoom and ProfileChatTab keep chip-only attachment rows. Forward marker `AD-720e-3` covers inline `<audio>` player inside chip surfaces if the Captain requests it. Rationale: (a) IntentSurface is the canonical chat-input render seam per HXI Principle #11 (workstation pattern); (b) WardRoom + Profile have no existing per-attachment render block to extend without inventing new structure; (c) collapses prompt scope from 3 components to 1 and removes 2 of 3 Required findings from pass 1.

---

## Section 5 — BUILDER-EXECUTION-PLAN: fold AD-738e-2 Refs-trailer rule

In `prompts/BUILDER-EXECUTION-PLAN.md`, find the **Standing Rules** section. After the existing `UI gate (BF-279, 2026-05-13)` bullet (per AD-738b), add a new bullet:

```markdown
- **Refs-trailer for orphan sub-ADs (AD-738e-2 / #653, Wave 159).** When a wave includes a sub-AD spawned from a parent BF that has no GH issue (e.g., AD-738e-1 born out of BF-285 commentary), the commit message has no `Closes #N` trailer. To preserve audit-trail traceability, the commit MUST include EITHER:
  - A `Refs #N-of-parent-BF` trailer when the parent BF has a GH issue, OR
  - A `See DECISIONS.md AD-NNN` reference in the commit body when the parent BF is internal-only.

  Builder applies this rule automatically when drafting commit messages for sub-AD work — no architect approval at GATE 2 required when the trailer is present. Lineage: AD-738e-1 (`bb1ca160`) shipped with the DECISIONS reference in the body; this codifies that as the standard.
```

Place this bullet immediately after the UI gate bullet. No other lines change in BUILDER-EXECUTION-PLAN.md.

---

## Test plan

Create `tests/test_ad720e_audio_attachments.py` with 4 pytest tests:

1. `test_audio_mpeg_id3_signature_validates` — bytes `b"ID3\x03\x00\x00..."` → `validate_magic_bytes("audio/mpeg", bytes)` returns True.
2. `test_audio_mp4_ftyp_signature_validates` — bytes `b"\x00\x00\x00\x20ftypM4A \x00..."` → True.
3. `test_audio_ogg_signature_validates` — bytes `b"OggS\x00..."` → True.
4. `test_audio_attachments_in_default_allowed_mimes` — `AttachmentsConfig().allowed_mime_types` includes all five audio MIMEs.

Create `ui/src/__tests__/IntentSurface.audioRender.test.tsx` with 3 vitest tests:

1. Render `IntentSurface` with `pendingAttachments=[{mime: "audio/mpeg", url: "/api/chat/attachments/abc", attachment_id: "abc"}]` → DOM has `<audio>` with that `src`.
2. Render with image attachment → DOM has `<img>` (regression check; ensures image path unaffected).
3. Render with `application/pdf` → DOM has file-icon fallback (regression check).

No real backend, no actual audio playback — pure DOM assertions.

---

## What this does NOT change

- Transcription / whisper.cpp — explicitly deferred (AD-705a remains forward marker).
- Vision pipeline / `vision_dispatch.py` — unchanged. Audio attachments never enter the multimodal-messages array.
- Attachment store SHA-ref invariant (AD-731) — audio bytes are stored exactly like images.
- AD-735 / AD-738 TTS surface — orthogonal (TTS writes audio TO the attachment store; this AD reads audio FROM the store for chat playback).
- Server-side recording / capture (operator-uploaded audio only in v1; AD-705a covers in-browser capture for chat).
- The AD-721b-1 lip-sync capture path — `audio/webm` + `audio/wav` were already accepted there, unchanged.
- The wave's other prompts (`ad-722c/d/b-3` / `ad-725`).

---

## Verification commands

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad720e_audio_attachments.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile
cd ui ; npx vitest run ; npm run build ; cd ..
```

**UI gate REQUIRED (AD-738b):** this prompt edits `ui/src/`, so the per-commit gate MUST run both `npx vitest run` AND `npm run build`.

---

## Tracker updates

- `PROGRESS.md` — append closure line (test count +4 pytest +3 vitest).
- `docs/development/roadmap.md` — mark #566 and #653 closed; AD-705a remains forward marker.
- `DECISIONS.md` — append AD-720e entry (and AD-738e-2 entry, both shipped in this wave commit). Document the AD-738e-2 numbering note (renumbering AD-738e-1's prosody forward marker to `AD-738e-2-prosody`). Update DECISIONS.md AD-738e-1 "Forward markers" line accordingly.

Commit message:
```
AD-720e + AD-738e-2: audio attachment playback + Refs-trailer standing rule

Closes #566
Closes #653
```

---

## License Disposition

**All-internal Apache 2.0.** No new pip deps (stdlib `bytes` matching only). No new npm deps — `<audio>` is a platform standard. No new model weights, no binaries (rhubarb / piper / Ollama all already in tree per AD-721b-1 / AD-738; no new external tooling). Three new MIME types all have permissive container specs; no patent-encumbered codec licensing concern at the playback layer (operator brings their own audio files; ProbOS just renders the existing `<audio>` element).

---

## Forward markers

- **AD-720e-1** — drop-zone visual feedback for audio file drag/drop (currently silent on hover — AD-730-1-2 forward marker still applies here).
- **AD-720e-2** — audio waveform thumbnail preview in attachment list (decode-on-demand via Web Audio API).
- **AD-720e-3** — inline `<audio>` player inside WardRoomThreadDetail and ProfileChatTab chip surfaces (post-scope-collapse, 2026-05-14 revision). Trigger: Captain wants to play audio without expanding into IntentSurface.
- **AD-705a** (unchanged) — whisper.cpp WASM transcription for chat audio; will inline the transcript into the prompt context similarly to AD-720d's text extraction.

---

## Acceptance criteria

- 4 new pytest + 3 new vitest tests pass.
- `npm run build` succeeds (the BF-279 regression class).
- Full gate `pytest tests/ -q -n 4 --dist=loadfile` green.
- Manual smoke (Captain-side, not test-required): drop an MP3 into a Counselor DM → renders `<audio controls>` → clicking play emits audio.
- `BUILDER-EXECUTION-PLAN.md` Standing Rules now lists the AD-738e-2 Refs-trailer rule.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-14)

```
grep -n "allowed_mime_types: list\[str\]" src/probos/config.py
  1124:     allowed_mime_types: list[str] = Field(
  (current list ends at line 1138 with "audio/wav")

grep -n "_SIGNATURES" src/probos/attachments/mime.py
  18: _SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
  27:     "audio/webm": [(0, b"\x1a\x45\xdf\xa3")],
  28:     "audio/wav":  [(0, b"RIFF"), (8, b"WAVE")],       # both required
  32: _ANY_OF: frozenset[str] = frozenset({"image/gif"})    # existing any-of mechanism
  48:     if declared_mime in _ANY_OF:                       # any-of branch in validator

grep -n "att.mime.startsWith('image/')" ui/src/components/IntentSurface.tsx
  1970:                       {att.mime.startsWith('image/') ? (

grep -n "startsWith('image/')" ui/src/components/wardroom/WardRoomThreadDetail.tsx
  182:     const imageItem = items.find(it => it.type && it.type.startsWith('image/'));

grep -n "AD-738e-1" DECISIONS.md
  2452: ### AD-738e-1 — Per-emotion Piper prosody overrides (Wave 158)
  2466: **Forward markers.** AD-738e-2 (noise_w / sentence_silence per-emotion overrides)...
```

**Builder must verify** before applying Section 2: read `src/probos/attachments/mime.py:35-58` (`validate_image_bytes`) and confirm the `_ANY_OF` branch at line 48 still has the `for offset, sig in sigs: ... return (True, declared_mime)` any-of loop. If the matcher has been refactored since 2026-05-14, adapt the Section 2 edit to the current matcher shape.

---

## Revision (2026-05-14)

**Pass 1 review:** `prompts/Reviews/ad-720e-audio-attachments-review.md` — Verdict ❌ Not Ready. Three Required findings.

**Applied:**

- **Required #1 (Section 2 invented `_ANY_OF_SIGNATURES`)**: dropped the invented mechanism. Section 2 now uses the existing `_ANY_OF: frozenset[str]` at `mime.py:32` (consulted by `validate_image_bytes` at line 48). Two surgical edits: (a) add MP3 / MP4 / Ogg entries to `_SIGNATURES`; (b) extend `_ANY_OF` literal with `audio/mpeg` and `audio/mp4`. `audio/ogg` stays out (single signature; default all-required path is equivalent for the trivial case). The "Section 2a — extend matcher" conditional is removed entirely. Approach documented in Section 2 body.

- **Required #2 (Section 5 ProfileChatTab targets non-existent structure)**: Section 5 removed in its entirety. Live grep confirms `ProfileChatTab.tsx` has no `handlePaste` handler and no `<img>` render branch — file-picker path uploads attachments and renders them as filename chips. The allow-list extension in Section 1 already extends the file picker through `ALLOWED_ATTACHMENT_MIMES`, so ProfileChatTab inherits audio support via the picker without any tsx edit. Old Section 6 (BUILDER-EXECUTION-PLAN fold) renumbered to Section 5.

- **Required #3 (Section 4 render-block extension targets non-existent structure)**: Section 4 retained only the `handlePaste` MIME-filter half (lines 179-200). The "Locate the thread message renderer / Likely a `<img src={...}>` near pendingAttachments" half is removed. WardRoom chips stay chips; audio playback is delivered through IntentSurface (Section 3 — the canonical input render seam per HXI Principle #11). A new forward marker `AD-720e-3` covers inline `<audio>` player inside chip surfaces if the Captain requests it later. Forward markers list updated.

**Recommended scope-collapse APPLIED.** Audio playback renders only in IntentSurface. WardRoom paste-filter still accepts audio MIMEs (so a Captain pasting audio into a WardRoom DM uploads correctly and the agent sees the attachment), but the WardRoom and ProfileChatTab chip-rendering surfaces stay chip-only. Operator-visible behavior closes issue #566 (drag MP3 into chat → renders `<audio>`) through IntentSurface, which is the canonical chat input. Vitest count remains 3 (IntentSurface render branches), pytest count remains 4 (magic-byte + allow-list); test plan unchanged. Files-to-Modify table updated to drop `profile/ProfileChatTab.tsx`. Forward markers list updated to add `AD-720e-3`.

**Deferred (Recommended-tier from review, not blocking):**
- Recommended #1 was the scope-collapse itself — applied above.
- Recommended #2 (AD-738e-2 numbering note) — no action needed; the review already approved the renumber. Builder dispatches DECISIONS.md AD-738e-1 forward-marker line edit before writing the new AD-738e-2 entry, per the existing Section 5 (was Section 6) Builder note.

**Self-check:** `_ANY_OF_SIGNATURES` is no longer referenced in the prompt body; confirmed by grep below.
