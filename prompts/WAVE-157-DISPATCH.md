# Wave 157 Dispatch — Server-streamed TTS via Piper (closes the lip-sync loop)

**Date:** 2026-05-13. **Architect:** Sean. **Mode:** Continuous build (one prompt = one commit).
**Theme:** Replace browser `SpeechSynthesisUtterance` with server-streamed Piper TTS so the audio bytes exist before playback — rhubarb runs on real audio, visemes arrive alongside, the AD-721b-2 capture limitation is bypassed.
**Estimated wall-time:** ~6-10h. **Estimated test count delta:** +14 to +18 (≥ 10 Python + ≥ 4 Vitest).

---

## Wave goal

Wave 155 shipped `rhubarb-lip-sync` (AD-721b-1) + browser audio-capture (AD-721b-2). Captain installed rhubarb 1.14.0 + flipped `lipsync.backend: "rhubarb"` — and the visemes never improved over the Wave 138 heuristic. Diagnosis: `SpeechSynthesisUtterance` is **not** routable through Web Audio in current browsers, so `MediaStreamDestination` records 0 bytes every call; `captureUtteranceAudio` honest-degrades to `null` 100% of the time. The architecture worked; the substrate doesn't ship the API.

Wave 157 closes the loop with **one prompt** that makes the **server** the source of audio bytes:

1. **AD-738** — Server-side TTS via Piper (MIT). New `src/probos/audio/tts/` module, new Pydantic `TTSConfig`, new `POST /api/avatars/tts` endpoint that synthesizes + stores in AttachmentStore + runs rhubarb in a single round-trip. Browser plays via `<audio>` element. `SpeechSynthesisUtterance` is preserved as the explicit honest-degrade fallback. Default config (`tts.backend = "browser"`) keeps Wave 156 behaviour exactly.

This was filed as forward marker AD-721b-2.3 at Wave 155 close — no GH issue exists. Wave 157 closes the marker.

---

## Inputs (read in full before any code)

1. `.github/copilot-instructions.md` — engineering / testing / logging / type-annotation rules. Every commit complies.
2. `prompts/BUILDER-EXECUTION-PLAN.md` — standing rules (test gate, working-tree integrity, log-and-degrade tiers).
3. The 1 prompt file for this wave:
   - `prompts/ad-721b-2-3-server-streamed-tts.md`
4. Parent context:
   - AD-721b-1 (rhubarb backend) — `src/probos/avatars/rhubarb_backend.py`, `src/probos/routers/avatars.py`. The new endpoint is added to the SAME router file; the rhubarb backend is reused as a direct internal call.
   - AD-721b-2 (browser capture) — `ui/src/audio/lipSyncCapture.ts`, `ui/src/audio/useLipSyncCapture.ts`. The hook is extended with an injection setter; the existing capture path stays as future-compat code.
   - AD-731 (refs not blobs) — load-bearing invariant. Audio bytes flow through `AttachmentStore.put` → sha256; the response carries only the ref.
   - AD-735 (per-agent volume) — applied to BOTH the server `<audio>` path and the SpeechSynthesis fallback.
   - AD-737 (per-agent emotion taxonomy) — `applyEmotionalModulation` runs before EITHER path.

---

## Standing rules (carry from Wave 156)

- **Test gate (full):** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`. Documented HEAD-flake set (excluded from regression budget): `test_callsign_routing` × 3, `test_ad719_chat_fanout` × 1, `test_ward_room::TestEndorsementActivation::test_browse_threads_sort_recent` × 1, `test_dreaming::TestDreamingIntegration::test_nl_to_dream_cycle_changes_weights` × 1. **Wave 157 must NOT regress this set.**
- **Per-prompt focused gate (Python):** `pytest tests/test_ad738_piper_tts.py -v -n 0`.
- **Per-prompt focused gate (UI):** `cd ui && npx vitest run src/audio/__tests__/voice.serverTts.test.ts src/audio/__tests__/useLipSyncCapture.test.tsx`.
- **Working tree:** if you find tracked-file modifications you didn't make, surface them. Do not `git stash` / `git reset --hard`. The 2026-05-08 wipe pattern is documented in `/memories/repo/probos-notes.md`.
- **One commit for this wave.** Commit message: `AD-738: Server-streamed TTS via Piper (Wave 157)`. No `Closes #NNN` line — AD-721b-2.3 was a forward marker, no GH issue exists.
- **AD-731 invariant.** Audio bytes go into `AttachmentStore` as content-addressable SHA-256 refs — never inline base64 in any RPC body. The new endpoint MUST return only `audio_attachment_id`. Test #16 (per Section 5a of the prompt) asserts this explicitly.
- **AD-734 pre-commit hook** (`.git/hooks/pre-commit`) auto-runs `tests/test_ad734_wire_shape_contract.py` when `vision_dispatch.py` / `llm_client.py` / `routers/chat.py` / `routers/agents.py` / `system.yaml` is staged. AD-738 touches `routers/chat.py` only via the `_get_attachment_store` import (no body changes); the hook will fire — that's fine, the bus shape is unchanged. Do NOT bypass with `--no-verify`.
- **NEVER broad-kill python by path** when cleaning up pytest workers. Use `scripts/kill-stale-pytest.ps1` (reads `data/probos.pid`, matches CommandLine, skips the live runtime). The 2026-05-12 incident memo is in user memory.
- **`multi_replace_string_in_file` is fragile** when replacement blocks are adjacent. Wave 154-156 BFs (BF-274, BF-278) are the canonical examples. For `voice.ts` Section 4a (which rewrites the existing `speakResponse` body), prefer ONE single `replace_string_in_file` call covering the whole function over multiple adjacent blocks.

---

## Pre-flight checklist (before drafting Builder dispatch)

Before the Builder starts:

1. **Working-tree integrity.** Run `git diff --numstat | Sort-Object {[int]$_.Split("`t")[1]} -Descending | Select-Object -First 5`. Any tracked file showing > 200 deletions = STOP and investigate.
2. **Baseline tests.** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` shows ONLY the documented HEAD-flake set (6 tests) red and nothing else. UI baseline: `cd ui && npx vitest run` is green.
3. **License confirmation #1 (binary):** `gh api repos/rhasspy/piper/license | jq .license.key` returns `"mit"`. Recorded in the AD-738 prompt's License Disposition section.
4. **License confirmation #2 (default voice model):** browse https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/amy/medium and confirm the model card declares **MIT** for `en_US-amy-medium`. Recorded in the License Disposition section. **Do not proceed if the voice license has changed since the prompt was drafted.**
5. **`.gitignore` coverage confirmed.** `Select-String -Path .gitignore -Pattern "^/tools/"` returns line 3. The Piper binary location `tools/piper/piper(.exe)` and the voice model location `tools/piper/voices/` are already gitignored — **no `.gitignore` edit needed in this wave.**
6. **AttachmentStore.put signature audit.** `Select-String -Path src/probos/attachments/filesystem_store.py -Pattern "def put\("`. Confirm the `mime` parameter exists and is keyword-acceptable. If positional-only, switch the call site in Section 3 of the prompt to positional args before commit.
7. **Operator action item (FOR THE OPERATOR, NOT THE BUILDER):** to manually smoke-test AD-738 post-merge, the operator drops:
   - `tools/piper/piper.exe` (Windows; from https://github.com/rhasspy/piper/releases)
   - `tools/piper/voices/en_US-amy-medium.onnx` AND `tools/piper/voices/en_US-amy-medium.onnx.json` (from https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/amy/medium)
   - Edit `config/system.yaml`: add `tts:\n  backend: "piper"` AND `lipsync:\n  backend: "rhubarb"` (rhubarb already installed from Wave 155).
   The Builder does NOT touch this directory; tests stub the subprocess via tmp_path scripts (mirrors AD-721b-1 pattern).
8. **Highest-AD verification.** `Select-String -Path DECISIONS.md -Pattern "^### AD-7\d\d"` confirms `AD-737` is the current highest. Wave 157 advances to **AD-738**. Forward markers AD-738a/b/c/d are filed in `roadmap.md` only — no DECISIONS.md entries until they're built.

---

## Build order

**One prompt, one commit.** No dependency DAG.

```
Group A (single prompt):
  AD-738  ─── Server-streamed TTS via Piper
```

---

## Per-prompt summary

| AD | GH | Files | Tests | Est |
|---|---|---|---|---|
| AD-738 | none (was forward marker AD-721b-2.3) | `src/probos/audio/__init__.py` (new), `src/probos/audio/tts/__init__.py` (new), `src/probos/audio/tts/backends.py` (new), `src/probos/audio/tts/piper_backend.py` (new), `src/probos/audio/tts/null_backend.py` (new), `src/probos/config.py` (TTSConfig + Config wire), `src/probos/routers/avatars.py` (new endpoint added to existing router), `tests/test_ad738_piper_tts.py` (new), `ui/src/audio/voice.ts` (modify speakResponse), `ui/src/audio/useLipSyncCapture.ts` (extend with injectLipSyncFrames), `ui/src/audio/__tests__/voice.serverTts.test.ts` (new), `ui/src/audio/__tests__/useLipSyncCapture.test.tsx` (extend with injection regression) | ≥ 10 Python + ≥ 4 Vitest + 1 regression | 6-10h |

---

## License posture

- **piper-tts (rhasspy): MIT.** Verified `gh api repos/rhasspy/piper/license` → `"key": "mit"` (2026-05-13). Top of permissive preference list.
- **`en_US-amy-medium` voice model: MIT.** Verified at https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/amy/medium model card.
- **No external code absorption.** ProbOS ships only the wrapper module + endpoint + browser modifications. The Piper binary and voice model files are operator-provided and never enter the repo.
- **No Python deps added.** `pyproject.toml` is unchanged.
- **No npm deps added.** `ui/package.json` is unchanged. The browser uses Web Audio + `<audio>` + `fetch` — all platform standards.
- **`.gitignore`** already covers `tools/` (line 3). No edit needed.
- **Excluded by design (License hygiene rule):**
  - **Coqui XTTS v2** — CPL non-commercial; **forbidden**. Do NOT propose as a backend in this wave or any future wave.
  - **Tortoise TTS** — Apache 2.0 OK but 5-10s latency; defer to AD-738b GPU eval.
  - **ElevenLabs** — proprietary cloud API; commercial-overlay-only candidate; not in this wave.

---

## Per-commit quality gate

After the AD-738 commit:

1. Run the focused Python test gate. Expect ≥ 10 new tests green.
2. Run the focused UI test gate. Expect ≥ 4 new + 1 regression green.
3. Run the full Python test gate. Confirm only the documented HEAD-flake set is red — nothing else.
4. Run the full UI test gate (`cd ui && npx vitest run`). Confirm green.
5. Confirm the AD-734 pre-commit hook fired (chat router import touched) and passed.
6. Verify `PROGRESS.md` was updated: highest-AD line advances from AD-737 → AD-738.
7. Verify `DECISIONS.md` AD-738 entry includes the License Disposition section AND the four forward markers (AD-738a/b/c/d).
8. Verify `docs/development/roadmap.md` has roadmap entries for AD-738a/b/c/d with their trigger conditions.

---

## Hard-stop conditions

Stop the wave and surface to architect immediately if:

- **Phantom API discovered** in the prompt that affects the implementation (not just test fixtures). Specifically: `AttachmentStore.put` signature mismatch with the prompt's call site, OR `_get_attachment_store` import path drift, OR `generate_visemes` parameter name drift since AD-721b-1.
- **AD-731 invariant violation** detected during build. If anyone proposes inlining audio bytes into the `/api/avatars/tts` response body or into `IntentMessage.params` to make a test easier — STOP. The BF-265 / wave-151 lesson is the canonical "inline blobs in RPC = OOM" precedent.
- **Test gate regresses past the documented HEAD-flake set.** Any new red test that isn't on the documented list = stop and triage.
- **`tts.backend = "browser"` default does NOT preserve Wave 156 behaviour.** The acceptance criterion is "operators who don't install Piper see ZERO change." Any test that asserts the `<audio>` path is taken when `backend = "browser"` is wrong — the fallback MUST run.
- **`speechSynthesis.speak` is no longer reached** in the documented honest-degrade chain. Any code path that loses the SpeechSynthesisUtterance fallback breaks the load-bearing invariant ("speech must NEVER stop because of a TTS failure").
- **Working tree shows tracked-file deletions** > 200 lines you didn't author. Run the deletion-check command BEFORE any analysis (per BUILDER-EXECUTION-PLAN.md).
- **`multi_replace_string_in_file` adjacent-block regression.** If the Builder uses `multi_replace_string_in_file` on `voice.ts` and the post-edit file has unexpected line losses (similar to the BF-274 / BF-278 vision_dispatch.py incident), revert and use single `replace_string_in_file` calls.

---

## GH issues to close

None. AD-721b-2.3 was a forward marker filed at Wave 155 close; no GH issue exists. The commit message omits the `Closes #NNN` line.

---

## Acceptance for the wave as a whole

- ✅ AD-738 committed (one commit, no Closes line).
- ✅ Full Python test gate green at end of wave; baseline + ≥ 10 new tests.
- ✅ Full UI test gate green at end of wave; baseline + ≥ 4 new Vitest + 1 regression.
- ✅ AD-734 pre-commit hook never bypassed.
- ✅ `PROGRESS.md` highest-AD line advances to AD-738.
- ✅ `progress-era-5-unification.md` gets one bullet for the shipped AD.
- ✅ Prompt file moved to `prompts/archive/` after wave close (orchestrator handles this).
- ✅ Orchestrator state advanced via `scripts/wave-orchestrator.ps1`.
- ✅ License Disposition recorded in the AD-738 entry in `DECISIONS.md` (Piper MIT + voice model MIT).
- ✅ Forward markers AD-738a/b/c/d filed in `roadmap.md` AND referenced in the AD-738 DECISIONS.md entry.
- ✅ Operator-facing smoke test instructions in the AD-738 entry (download Piper + voice model, drop in `tools/piper/`, set `tts.backend: "piper"`, restart, send a DM).

---

## Deferrals — explicit forward markers

The following are **explicitly out of scope** for Wave 157:

- **AD-738a** — Per-agent voice selection. `CrewProfile.voice_model` field + selector UI in `ProfileInfoTab.tsx`; surfaces voice license in the picker. Build when operator has > 2 voice models installed.
- **AD-738b** — GPU-accelerated TTS backend evaluation. Kokoro (Apache 2.0, ~80 MB, GPU optional) and StyleTTS2 (MIT, GPU recommended) both slot into the `TTSBackend` Protocol added in AD-738. Build when operator with capable GPU (e.g. 5090) requests higher fidelity.
- **AD-738c** — Server-side voice modulation. Apply AD-735 pitch/rate per-agent at the Piper synthesis step rather than `<audio>` post-processing. Closes the "no pitch on `<audio>` element" limitation noted in the prompt's Section 4a.
- **AD-738d** — TTS text caching layer. LRU cache keyed `(agent_id, voice, sha256(text))` → `attachment_id`. Build when telemetry shows the same text re-synthesizing repeatedly in a session window.
- **AD-721b-3** — whisper.cpp WASM tiny.en for offline phoneme alignment ([#561](https://github.com/seangalliher/ProbOS/issues/561)). Stays open; separate path.

All forward markers MUST be tracked in `docs/development/roadmap.md` before wave close (per repo memory rule). For Wave 157, AD-738a/b/c/d are roadmap-only; AD-721b-3 / #561 was tracked at Wave 155 close.
