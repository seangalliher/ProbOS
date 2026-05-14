# Review: AD-738e-1 — Per-emotion Piper prosody overrides
**Verdict:** ⚠️ Conditional
**One-line headline.** Architecturally sound additive feature with backward-compat preserved, but Section 6's cross-module use of a private helper (`_resolve_intent_name`) needs a public API or a smaller resolution path; one fabricated cross-prompt authorization claim must be removed.

## Required (must fix before building)
1. **Fabricated cross-prompt authorization claim.** Section 6 imports `_resolve_intent_name` (underscore-prefixed = module-private) from `divergence_detector.py` inside `routers/agents.py`, and justifies it with: *"`_resolve_intent_name` is module-private but the AD-737a doc-contract section explicitly authorizes import for v1 resolution."* I verified AD-737a's prompt — its Section 3 docstring documents `runtime.profile_store` / `divergence_results` / `divergence_history` test-fake contract only; it does **NOT** authorize cross-module import of `_resolve_intent_name`. This is a copilot-instructions Demeter / open-closed violation ("Extend via public APIs, not private member patching"). Fix one of two ways:
   - **Option A (preferred, cheap):** Add a public alias in `divergence_detector.py` — e.g., `def resolve_intent_to_v1(name, custom_emotions): return _resolve_intent_name(name, custom_emotions)` — and import THAT from the chat router. 2-line change in the avatars module.
   - **Option B (preferred long-term):** Land the cross-prompt synergy with AD-737a — add a `resolved_v1_emotion: str | None` field to `DivergenceResult`, populate it in the single-pass collapse, and Section 6 becomes `_emotion = result.resolved_v1_emotion`. AD-737a is already touching `apply_divergence_check` in the same wave; the merge is natural.

   Either way, remove the fabricated "AD-737a authorizes" sentence.

## Recommended
1. **Section 6 boundary-test missing.** The 6 pytest tests cover prosody resolver, PiperBackend, and the avatars endpoint. There is no test that the chat-router response dict actually contains the `emotion` field after a real custom-emotion divergence. Add a 7th test: build a runtime with `divergence_results[agent_id] = DivergenceResult(intent_emotion="professional_concern", ...)` and a `profile_store` exposing `custom_emotions={"professional_concern": EmotionProfile(inherits="concerned", ...)}`; assert the chat response dict's `emotion` field == `"concerned"` (v1, post-resolve).
2. **Section 4 import-inside-function smell.** The prompt instructs adding `from probos.audio.tts.prosody import resolve_prosody_overrides` inside the `synthesize` method body. The repo convention (and copilot-instructions) is module-top imports unless a circular dep forces lazy import. There is no circular dep here — both modules live under `src/probos/audio/tts/`. Move the import to module-top.
3. **Section 5 boundary validation is asymmetric.** `if not isinstance(emotion, str) or len(emotion) > 32 or not emotion.strip(): emotion = None`. The 32-char cap is unjustified — actual v1 emotion names max at ~12 chars (`apologetic`) and custom names go up to whatever the manifest allows. Either tighten to `> 64` to comfortably cover custom name pass-through (defense-in-depth) OR document the 32-char value with a reference. Minor.

## Nits
1. Section 6 line count: 18 lines of nested logic for a derived value. After Required #1 fix, this collapses naturally.
2. Section 7's `_body` local-variable name uses underscore prefix — convention in this file is camelCase locals. `body` is taken; use `requestBody` or inline the object literal.
3. Section 8 — Builder note "if the chat-response variable name is not `data`, substitute the actual name." Verified: it IS `data` at line 121, so the builder will not need to substitute. Nit can drop.
4. PiperBackend constructor defaults `noise_scale=0.85`, `length_scale=1.0` (verified at piper_backend.py:75-78). The override table's `concerned` value (`0.95`) is *higher* than baseline `0.85` — more variation in concerned voice. The `formal` value `0.70` is lower — drier. Override values match Captain's intent. ✓
5. The 4 forward markers (AD-738e-2/-3/-4) are well-scoped follow-ups.

## Verified
- `EmotionalIntent` enum at [divergence_detector.py#L35](src/probos/avatars/divergence_detector.py#L35).
- `_resolve_intent_name` at [divergence_detector.py#L94](src/probos/avatars/divergence_detector.py#L94) — accepts `(name, custom_emotions)`, returns v1 name or None. Logic matches prompt's claim.
- `class TTSBackend(Protocol)` at [backends.py#L23](src/probos/audio/tts/backends.py#L23); `synthesize` at line 33.
- `PiperBackend.synthesize` at [piper_backend.py#L88](src/probos/audio/tts/piper_backend.py#L88); subprocess args at lines 141-144 use `self._noise_scale` etc. — refactor to local vars is clean.
- `select_backend(backend_name, config)` at [tts/__init__.py#L16](src/probos/audio/tts/__init__.py#L16). **Signature does NOT change** — only `backend.synthesize` gains a kwarg. Blast radius is internal to TTS backends. ✓
- `_synthesize_tts_impl` at [routers/avatars.py#L143](src/probos/routers/avatars.py#L143); `backend.synthesize(text)` call at [routers/avatars.py#L167](src/probos/routers/avatars.py#L167).
- Response dict in `routers/agents.py` at line 1370 — `{"response": response_text, "callsign": callsign, "agentId": agent_id}` matches prompt.
- `divergence_results` populated by `apply_divergence_check` at `divergence_detector.py:454`, *before* the chat router builds the response dict. Ordering invariant holds.
- `speakResponse` at [voice.ts#L167](ui/src/audio/voice.ts#L167); current sig is `(text, profile?, agent_id?)`. New kwarg appended in keyword-only style — backward compat for all 1 existing caller (ProfileChatTab.tsx:124).
- `JSON.stringify({ text })` at [voice.ts#L209](ui/src/audio/voice.ts#L209).
- ProfileChatTab.tsx — `const data = await res.json();` at line 121, `speakResponse(stripMarkdownForSpeech(reply), voiceProfile ?? undefined, agentId);` at line 124. Variable name `data` is correct.
- "Additive only" invariant: `resolve_prosody_overrides(None) == {}` → PiperBackend keeps constructor defaults. No regression possible for existing audio paths.
- AD-731 attachment invariant preserved (audio bytes still flow through AttachmentStore).
- HXI: no new UI surface; audio-only change. ✓
- License: all-internal. No pip/npm deps. ✓
- BF-279 UI gate: prompt runs `npm run build` in verification commands. ✓
- Vitest 2 tests cover happy + backward-compat paths.
- Forward markers AD-738e-2 (noise_w / sentence_silence), -3 (per-agent override), -4 (UI tuning surface) — well-scoped, deferred correctly.

### Re-review (pass-2): 2026-05-13

**Verdict (final):** ✅ Approved (Required cleared; no new Required introduced).

**Revision check — option (b) applied correctly.**
- Section 5b adds the public alias `resolve_emotion_to_v1 = _resolve_intent_name` in `src/probos/avatars/divergence_detector.py` immediately below the private helper. Same signature, same return contract. ✓
- Section 6 now imports the alias at module-top (`from probos.avatars.divergence_detector import resolve_emotion_to_v1`) and the body calls `resolve_emotion_to_v1(_raw, _custom)`. No `_resolve_intent_name` reference remains in `routers/agents.py`. ✓
- Fabricated "AD-737a doc-contract section explicitly authorizes import for v1 resolution" parenthetical is gone. Replaced with "Uses the public ``resolve_emotion_to_v1`` alias (AD-738e-1 Section 5b) — no cross-module private access." ✓
- AD-737a is NOT modified. Single-prompt fix; no cross-prompt coordination required. ✓

**Recommended items — all folded in:**
- Rec #1 (chat-router boundary test) → Test 7 added (`test_chat_response_includes_resolved_v1_emotion_for_custom_name`); test count 6 → 7; PROGRESS.md tracker updated.
- Rec #2 (inline import smell) → moved `from probos.audio.tts.prosody import resolve_prosody_overrides` to module-top of `piper_backend.py`.
- Rec #3 (32-char cap) → bumped to `> 64` for defense-in-depth headroom on custom emotion names.

**New findings introduced by revision:** None Required, none Recommended. One Nit:
- **Nit (new):** `## Files to Modify` table (line 45) does NOT list `src/probos/avatars/divergence_detector.py` as a modified file, even though Section 5b adds the 3-line public alias there. Builder will still find the change via Section 5b body, but the file-list summary is now incomplete. Non-blocking — Builder reads the prompt linearly and Section 5b is explicit about the file and insertion location.

**Verdict re-affirmed:** ✅ Approved. Required cleared cleanly via option (b) (public alias, additive, no AD-737a coupling). Recommended all folded in. One trivial new Nit on the file-list table. Ready for GATE 1 dispatch.
