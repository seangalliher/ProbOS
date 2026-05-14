# Wave 157 — Pass 1 Sweep Summary

**Date:** 2026-05-13
**Reviewer:** Architect (Copilot)
**Prompts in wave:** 1 — `ad-721b-2-3-server-streamed-tts.md` (AD-738)
**Verdict:** ⚠️ **Conditional — REVISE then REVIEW (no architectural problem; 3 surgical fixes)**

---

## Per-prompt verdicts

| Prompt | Verdict | One-line justification |
|---|---|---|
| AD-738 — Server-streamed TTS via Piper | ⚠️ Conditional | Phantom `AttachmentStore.put`, default-config HTTP regression, and one buggy code block in Section 2e — all three are small surgical fixes; design is sound. |

---

## Total Required findings

**3.**

1. Phantom API: `await store.put(result.audio_bytes, mime=result.mime)` in Section 3. The live Protocol exposes `write(content_hash, blob, mime) -> Path`; caller computes the sha256 via `hashlib`. Same pattern as [chat.py:665-692](../../src/probos/routers/chat.py#L665).
2. Default-config (`tts.backend = "browser"`) regression: every `speakResponse()` now incurs a `/api/avatars/tts` HTTP RTT before falling back. Wave 156 had zero HTTP. Violates the "ZERO change" acceptance criterion. Add a server-feature probe cache in `voice.ts`.
3. Section 2e canonical `create_subprocess_exec` block contains `--output_raw -` which the prose then says to delete. Builder will copy-paste verbatim. Inline the corrected block; demote the explanation to a `# NOTE` comment.

---

## Highest-risk areas in the prompt

1. **Section 3 endpoint write-side** — uses a non-existent method (`put`). This is the canonical "phantom API in the implementation, not just the test" hard-stop pattern (see WAVE-157-DISPATCH "Hard-stop conditions"). Without the fix, Builder's first integration test against `FilesystemAttachmentStore` will `AttributeError` immediately.

2. **Section 4a default-config behaviour** — the load-bearing acceptance criterion is "operators who don't install Piper see ZERO behaviour change." The current `voice.ts` rewrite makes a network call on every utterance even when `backend = "browser"`. This is the kind of "performance regression nobody notices in tests but the Captain notices in 10 minutes" pattern. The fix shape is one module-level boolean cache + a probe.

3. **Section 2e implementation correctness** — `multi_replace_string_in_file` adjacent-block bug (BF-274 / BF-278 lineage) lurks here because the prompt has the wrong code in a canonical block AND a correction in surrounding prose. The Builder's safest path is to copy the canonical block; the safest *correct* path requires reading the prose. Inlining the fix removes the foot-gun.

---

## What is solid

- License posture (MIT-only, operator-provided binary + voice model, `/tools/` already gitignored).
- AD-731 ref-shape invariant preserved (response carries only `audio_attachment_id`).
- AD-735 / AD-737 modulation preserved on both the server-path and the SpeechSynthesis fallback via shared `_resolveEffectiveProfile` helper.
- Honest-degrade chain documented as a 3-tier table; SpeechSynthesisUtterance fallback is preserved verbatim.
- `useLipSyncCapture` injection pattern is additive; existing capture path stays as future-compat code.
- Subprocess discipline mirrors AD-721b-1 (`create_subprocess_exec`, no `shell=True`, absolute resolved binary path, timeout with `kill()`, stderr captured).
- Highest-AD numbering verified (`AD-737` → `AD-738`); forward markers `AD-738a/b/c/d` filed correctly as roadmap-only entries.
- HXI principles respected (no UI surface added; `<audio>` element never mounted to the DOM).

---

## Recommendation

**REVISE** (not RE-DRAFT).

The architectural shape is correct: server is the source of audio bytes, AttachmentStore is the persistence seam, rhubarb is reused as a direct internal call, browser plays via `<audio>` and falls back honestly. The 3 Required findings are: one wrong method name, one unconditional fetch that should be conditional, and one mis-placed code block. Each is a 5-15 minute fix. No architectural rework required. After revision, expect a single-pass approval.

**Author action:** address the 3 Required findings; consider the 6 Recommended (especially #1 unused `agent_id` field and #4 type-loosening of `select_backend`); apply Nits at author discretion. Re-submit for pass 2.

---

## Builder dispatch posture

**HOLD** until pass 2. Do NOT dispatch the current draft — Required #1 (phantom `put`) will block Builder's first endpoint test, and Required #2 (default-config regression) will silently degrade the operator experience without test failure.

---

## Process notes for Wave 157

- Pre-flight item 6 in WAVE-157-DISPATCH ("AttachmentStore.put signature audit") frames the question as "does it accept `mime=` as a kwarg?" The deeper question is "does the method exist at all?" Update the pre-flight wording so the next wave's pre-flight catches the method-name class of phantom, not just the kwarg-shape variant.
- Architect's two open items in the user request:
  - **(a) `AttachmentStore.put` mime kwarg** — answered above. Method does not exist; use `write(hash, blob, mime)`.
  - **(b) Should `tts.backend = "piper"` imply `lipsync.backend = "rhubarb"` automatically?** Recommendation: **NO**. Keep them orthogonal. Operator may want server-streamed TTS without rhubarb (e.g., on a host without rhubarb installed) — endpoint already handles this case (`visemes_payload = []` when `lipsync.backend != "rhubarb"`). The implicit cross-coupling would be a magic-config trap. The current design is correct; the prompt should add one explanatory sentence to the operator smoke-test instructions noting that `lipsync.backend = "rhubarb"` is the OTHER half of the loop and the operator opts in independently.
