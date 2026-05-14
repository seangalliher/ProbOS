# Review: AD-720e — Audio attachment playback (+ AD-738e-2 Refs-trailer fold)

**Verdict:** ❌ Not Ready
**Three Required fixes: (1) magic-byte matcher mechanism already exists under a different name than the prompt invents; (2) ProfileChatTab Section 5 targets a structure that does not exist; (3) WardRoomThreadDetail "message renderer" cited in Section 4 also does not exist (only chip-style pending render). The AD-738e-2 numbering renumber and the IntentSurface Section 3 + magic-byte signatures + config allow-list are all clean — this is purely a UI-scope + mime-matcher-naming defect set.**

## Required (must fix before building)
1. **Section 2 reinvents an existing mechanism.** Prompt instructs Builder to "extend matcher with `_ANY_OF_SIGNATURES` dict" if the current rule is all-required. The actual existing primitive is `_ANY_OF: frozenset[str] = frozenset({"image/gif"})` at `src/probos/attachments/mime.py:32`, consulted by `validate_image_bytes` at line 48 (`if declared_mime in _ANY_OF: ...`). The fix is **one line**: add `"audio/mpeg"` and `"audio/mp4"` to the `_ANY_OF` frozenset literal. `audio/ogg` has a single signature so it stays out. Rewrite Section 2 to use the existing mechanism by name; drop the conditional matcher-extension language and the invented `_ANY_OF_SIGNATURES`. The prompt's verify-first block did not grep `_ANY_OF` — add that line.
2. **Section 5 (ProfileChatTab) targets non-existent structure.** ProfileChatTab.tsx has **no `handlePaste` handler, no `<img>` render branch, no `mime.startsWith('image/')` check**. Attachments are surfaced as filename chips only (lines 235-258). The prompt's "mirror Section 4 edits" is non-actionable. Either (a) drop Section 5 entirely (ProfileChatTab uses the file-picker via `ALLOWED_ATTACHMENT_MIMES` — Section 1's allow-list extension is sufficient there) OR (b) replace Section 5 with a chip-level extension that surfaces `<audio controls>` inline when the chip's MIME starts with `audio/` AND add a `handlePaste` handler if pasted-audio is in scope. Be explicit about which.
3. **Section 4 (WardRoomThreadDetail message renderer) also non-existent.** WardRoomThreadDetail.tsx renders attachments only as filename chips (line 286: `{a.filename || a.attachment_id.slice(0, 12)}`). There is no `<img src=...>` block for posted-message attachments. The prompt's "Locate the thread message renderer... grep this same file for where pending OR posted attachments are rendered to the DOM. Likely a `<img src={...}>` near pendingAttachments OR a posted-message render block" describes structure that doesn't exist. The `handlePaste` MIME-filter extension at line 182 (Section 4 first half) is fine and necessary. The render-block extension is the part that needs rescoping — same options as for Section 5.

## Recommended
1. **IntentSurface Section 3 is the only render seam that currently has an `<img>` branch.** Consider scoping the AD to "playback in IntentSurface; chip-only in WardRoom/ProfileChatTab; AD-720e-3 forward marker for inline player in chip surfaces." This collapses Sections 4 + 5 into a single Section-4: extend `handlePaste` to accept audio MIMEs in both files, full-stop. Cleaner scope, same closure for issue #566.
2. **AD-738e-2 fold is on the right side of the line** — `BUILDER-EXECUTION-PLAN.md` Standing Rules edit is one bullet, and the renumber of the prosody marker is documented in both the prompt and `WAVE-159-DISPATCH.md`. The numbering reuse is acceptable per the standing rule that unbuilt forward markers can be renumbered (Wave-158 precedent). No flag.

## Nits
1. The AD-738e-1 forward-marker line in `DECISIONS.md:2569` is the single line to update: "AD-738e-2 (noise_w / sentence_silence per-emotion overrides)" → "AD-738e-2-prosody (noise_w / sentence_silence per-emotion overrides)". The prompt's Tracker section captures this. Make sure the Builder dispatches DECISIONS.md edit BEFORE writing the new `AD-738e-2` entry to avoid line-shift conflicts.
2. The "Operator brings their own audio files; ProbOS just renders the existing `<audio>` element" license note is correct and important — codecs (MP3, AAC) carry no patent obligation at the playback layer in 2026; mention "browser provides the decoder" for clarity.

## Verified
- `AttachmentsConfig.allowed_mime_types` `default_factory=lambda: [...]` at `src/probos/config.py:1124`. Existing audio entries `audio/webm` and `audio/wav` present. Insertion seam clean.
- `_SIGNATURES` dict at `attachments/mime.py:18`; `_ANY_OF` frozenset at line 32; existing `audio/wav: [(0, RIFF), (8, WAVE)]` correctly uses all-required (both sub-magic-bytes ARE required for valid WAV). The any-of mechanism is established prior art (image/gif).
- IntentSurface `att.mime.startsWith('image/')` ternary at `IntentSurface.tsx:1970` — confirmed; Section 3's image→audio→fallback 3-way render extension is correct and well-formed.
- WardRoomThreadDetail `handlePaste` at line 178 + `imageItem = items.find(it => it.type && it.type.startsWith('image/'))` at line 182 — first half of Section 4 (MIME-check extension) is fine.
- AD-731 invariant preserved — audio bytes go through `AttachmentStore` SHA-256 ref; no inline base64. ✓
- HXI Principle #3 (no emoji): Section 3's render uses inline SVG file-icon and native `<audio controls>`. Compliant.
- AD-738b UI gate: verification commands include `cd ui ; npx vitest run ; npm run build`. Correct.
- DECISIONS.md AD-738e-1 forward-marker line at line 2569 — renumber target located.
- Test plan: 4 pytest (magic-byte + allow-list) + 3 vitest (audio/image/fallback render). Boundary coverage of the parts that ARE actionable is met.

---

**Re-review:** _(blocked on Sections 2, 4, 5 rewrites)_

### Re-review (pass-2, 2026-05-14)

**Verdict:** ✅ Approved.

**Required #1 (Section 2 reinvents existing mechanism) — RESOLVED.** Section 2 now titled "Magic-byte signatures (extend existing `_ANY_OF` mechanism)". Live-verified against `src/probos/attachments/mime.py`:
- `_SIGNATURES: dict[str, list[tuple[int, bytes]]]` at line 18 — confirmed.
- `_ANY_OF: frozenset[str] = frozenset({"image/gif"})` at line 32 — confirmed.
- `validate_image_bytes` at line 36 with the `if declared_mime in _ANY_OF:` branch at line 48 — confirmed.

Prompt's Section 2 "Edit 2 — extend `_ANY_OF` frozenset (`mime.py:32`)" matches the live primitive exactly (frozenset literal at line 32, gain entries `audio/mpeg` + `audio/mp4`, `audio/ogg` correctly stays out as single-signature). The invented `_ANY_OF_SIGNATURES` direction is gone. Files-to-Modify table row updated to cite `~32 (_ANY_OF)`.

**Required #2 (Section 5 ProfileChatTab) — RESOLVED.** Section 5 (ProfileChatTab edits) is removed in its entirety. Prompt now has exactly 5 `## Section` headers:
1. `AttachmentsConfig.allowed_mime_types` defaults
2. Magic-byte signatures (extend existing `_ANY_OF` mechanism)
3. IntentSurface audio render
4. WardRoomThreadDetail paste filter (MIME-only; no render extension)
5. BUILDER-EXECUTION-PLAN: fold AD-738e-2 Refs-trailer rule

The old Section 5 (ProfileChatTab mirror) is gone; the old Section 6 (BUILDER-EXECUTION-PLAN fold) is renumbered to 5. ProfileChatTab is correctly carried by Section 1's allow-list extension through `ALLOWED_ATTACHMENT_MIMES` (picker path), no tsx edit needed.

**Required #3 (Section 4 WardRoom render block) — RESOLVED.** Section 4 is now titled "WardRoomThreadDetail paste filter (MIME-only; no render extension)". The render-block half is removed; only the `handlePaste` MIME-filter at line 182 is touched. Files-to-Modify table row makes the constraint explicit: "Extend paste MIME-check to include `audio/`. **No render extension** — chip-only rendering preserved (scope-collapse, see Section 4)."

**Forward marker AD-720e-3 — DOCUMENTED.** Prompt Forward Markers section (line 259): "**AD-720e-3** — inline `<audio>` player inside WardRoomThreadDetail and ProfileChatTab chip surfaces (post-scope-collapse, 2026-05-14 revision). Trigger: Captain wants to play audio without expanding into IntentSurface." Captures the deferred chip→render extension cleanly.

**Scope-collapse hard-rule check:** vitest count unchanged at 3 (IntentSurface render branches: audio / image / fallback); pytest count unchanged at 4 (magic-byte + allow-list); AD-738b UI gate still triggered (`npm run build` retained). License note retained. AD-731 invariant retained.

No new Required findings. Recommended/Nits from pass 1 either addressed by the scope-collapse (#1) or unchanged (#2, nits).
