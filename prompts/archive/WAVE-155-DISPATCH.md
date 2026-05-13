# Wave 155 Dispatch — Phoneme-accurate lip-sync v2 (real audio + real visemes)

**Date:** 2026-05-12. **Architect:** Sean. **Mode:** Continuous build (one prompt = one commit).
**Theme:** Replace the AD-721b v1 heuristic phoneme schedule with real visemes derived from real audio. Closes both forward markers from Wave 138.
**Estimated wall-time:** ~6-10h. **Estimated test count delta:** +17 to +22 (≥ 10 Python + ≥ 7 Vitest).

---

## Wave goal

AD-721b v1 (Wave 138) shipped a text-only viseme heuristic — every utterance produces a phoneme schedule from the literal characters of the response, regardless of how the agent actually pronounces it. The mouth opens; "cat" and "cot" look identical. Counselor (Echo) flagged this on the v1 follow-up.

Wave 155 ships v2 in two paired prompts:

1. **AD-721b-1** — Server-side rhubarb-lip-sync wrapper. Takes real audio (sha256 ref to a previously-uploaded blob), runs the MIT-licensed `rhubarb` binary, returns a real viseme schedule. Honest-degrade when the binary is absent.
2. **AD-721b-2** — Browser-side real-audio capture. Captures the SpeechSynthesisUtterance audio via Web Audio + MediaRecorder, uploads as an AttachmentStore ref (NOT inline base64 — AD-731 invariant), POSTs to the AD-721b-1 endpoint, feeds the resulting frames to CrewVRM. Honest-degrade through to the AD-721b v1 heuristic when capture fails.

The two prompts together close [#559](https://github.com/seangalliher/ProbOS/issues/559) and [#560](https://github.com/seangalliher/ProbOS/issues/560). The third forward marker [#561](https://github.com/seangalliher/ProbOS/issues/561) (whisper.cpp WASM) is **explicitly NOT in this wave** — separate path, separate AD.

---

## Inputs (read in full before any code)

1. `.github/copilot-instructions.md` — engineering / testing / logging / type-annotation rules. Every commit complies.
2. `prompts/BUILDER-EXECUTION-PLAN.md` — standing rules (test gate, working-tree integrity, log-and-degrade tiers).
3. The 2 prompt files for this wave:
   - `prompts/ad-721b-1-rhubarb-lipsync-backend.md`
   - `prompts/ad-721b-2-browser-real-audio-capture.md`
4. Parent context: AD-721b v1 entries at `decisions-era-4-evolution.md:5170` and `DECISIONS.md:1592`. The v1 implementation in `ui/src/audio/lipSyncTrack.ts`.

---

## Standing rules (carry from Wave 154)

- **Test gate (full):** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`. Documented HEAD-flakes (excluded from regression budget): `test_callsign_routing` × 3, `test_ad719_chat_fanout` × 1, `test_ward_room::TestEndorsementActivation::test_browse_threads_sort_recent` × 1, `test_dreaming::TestDreamingIntegration::test_nl_to_dream_cycle_changes_weights` × 1.
- **Per-prompt focused gate (Python):** `pytest tests/test_<adNNN>_*.py -v -n 0`.
- **Per-prompt focused gate (UI):** `cd ui && npx vitest run src/audio/__tests__/<file>.test.ts` (or `.tsx`).
- **Working tree:** if you find tracked-file modifications you didn't make, surface them. Do not `git stash` / `git reset --hard`. The 2026-05-08 wipe pattern is documented in `/memories/repo/probos-notes.md`.
- **One commit per AD.** Commit message: `AD-721b-N: <one-line summary> (Wave 155)`. Include `Closes #NNN` for the GH issue retired by the commit.
- **AD-731 invariant.** Anything that goes into `IntentMessage.params` and could exceed 4 KB MUST use a content-addressable ref to `AttachmentStore`. Audio blobs in this wave fall under this rule — refs only on the bus / RPC paths.
- **AD-734 pre-commit hook** (`.git/hooks/pre-commit`) auto-runs `tests/test_ad734_wire_shape_contract.py` when vision_dispatch / llm_client / chat router / agents router / system.yaml is staged. AD-721b-1 touches the chat router peripherally (importing `_get_attachment_store` only); the hook will fire — that's fine, the bus shape is unchanged. Do NOT bypass with `--no-verify`.
- **NEVER broad-kill python by path** when cleaning up pytest workers. Use `scripts/kill-stale-pytest.ps1` (reads `data/probos.pid`, matches CommandLine, skips the live runtime). The 2026-05-12 incident memo is in user memory.

---

## Pre-flight checklist (before drafting Builder dispatch)

Before the Builder starts:

1. **Working-tree integrity.** Run `git diff --numstat | Sort-Object {[int]$_.Split("`t")[1]} -Descending | Select-Object -First 5`. Any tracked file showing >200 deletions = STOP and investigate.
2. **Baseline tests.** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` shows the documented HEAD-flake set (6 tests) and nothing else red. UI baseline: `cd ui && npx vitest run` is green.
3. **License confirmation.** `gh api repos/DanielSWolf/rhubarb-lip-sync/license | jq .license.key` returns `"mit"`. Recorded in both prompt files' License Disposition section.
4. **`.gitignore` coverage confirmed.** `Select-String -Path .gitignore -Pattern "^/tools/"` returns line 3. The rhubarb binary location `tools/rhubarb/rhubarb(.exe)` is already gitignored — **no `.gitignore` edit needed in this wave**.
5. **Operator action item (FOR THE OPERATOR, NOT THE BUILDER):** to manually smoke-test AD-721b-1 post-merge, the operator drops the rhubarb binary at `tools/rhubarb/rhubarb.exe` (Windows). Download from https://github.com/DanielSWolf/rhubarb-lip-sync/releases. The Builder does NOT touch this directory; tests stub the subprocess.
6. **Highest-AD verification.** Read `PROGRESS.md`. Confirm `AD-734` is the current top-level highest. Wave 155 adds two sub-ADs (AD-721b-1, AD-721b-2) under the existing AD-721b parent — the highest top-level number does NOT advance.

---

## Build order and dependency DAG

**Strict sequencing.** AD-721b-2 consumes the endpoint shipped by AD-721b-1 — the order is hard.

```
Group A (independent, single prompt):
  AD-721b-1  (#559)  ─── server-side rhubarb wrapper + POST /api/avatars/lipsync

Group B (depends on A):
  AD-721b-2  (#560)  ─── browser capture + CrewVRM consumer wiring
```

**Commit order: AD-721b-1, then AD-721b-2.** Two commits, one per AD.

---

## Per-prompt summaries

| AD | GH | Files | Tests | Est |
|---|---|---|---|---|
| AD-721b-1 | [#559](https://github.com/seangalliher/ProbOS/issues/559) | `src/probos/avatars/__init__.py` (new), `src/probos/avatars/rhubarb_backend.py` (new), `src/probos/config.py` (LipSyncConfig + Config wire), `src/probos/routers/avatars.py` (new), `src/probos/runtime.py` (router wire), `tests/test_ad721b1_rhubarb_backend.py` (new) | ≥ 10 Python | 3-5h |
| AD-721b-2 | [#560](https://github.com/seangalliher/ProbOS/issues/560) | `ui/src/audio/lipSyncCapture.ts` (new), `ui/src/audio/useLipSyncCapture.ts` (new), `ui/src/audio/__tests__/lipSyncCapture.test.ts` (new), `ui/src/audio/__tests__/useLipSyncCapture.test.tsx` (new), `ui/src/components/profile/CrewVRM.tsx` (consumer wire), `ui/src/__tests__/CrewVRM.realAudioFallback.test.tsx` (new) | ≥ 7 Vitest + 1 regression | 3-5h |

---

## License posture

- **rhubarb-lip-sync (DanielSWolf): MIT.** Verified `gh api repos/DanielSWolf/rhubarb-lip-sync/license` → `"key": "mit"`. Top of permissive preference list.
- **No external code absorption.** ProbOS ships only the wrapper module + endpoint + browser hook. The rhubarb binary is operator-provided and never enters the repo.
- **No Python deps added.** `pyproject.toml` is unchanged.
- **No npm deps added.** `ui/package.json` is unchanged. The browser hook uses Web Audio + MediaRecorder + fetch — all platform standards.
- **`.gitignore`** already covers `tools/` (line 3). No edit needed.

---

## Per-commit quality gate

After **each** commit:

1. Run the focused test gate for that AD's tests.
2. Run the full Python test gate. Confirm only documented HEAD-flakes are red.
3. Run the full UI gate (`cd ui && npx vitest run`). Confirm green.
4. Confirm the AD-734 pre-commit hook either fired and passed (AD-721b-1 commit, since chat router import is touched) or did not need to fire (AD-721b-2 commit).
5. Verify `PROGRESS.md` was updated for the AD just shipped.

---

## Hard-stop conditions

Stop the wave and surface to architect immediately if:

- **Phantom API discovered** in either prompt that affects the implementation (not just test fixtures). Specifically: a referenced helper that doesn't exist in the codebase, OR a function signature in the prompt that doesn't match the live signature.
- **AD-731 invariant violation** detected during build (e.g. someone proposes inlining audio bytes into an RPC body to make a test easier — STOP, that pattern is the BF-265 / wave-151 lesson).
- **Test gate regresses past the documented HEAD-flake set.** Any new red test that isn't on the documented list = stop and triage.
- **AD-734 pre-commit hook fires red** on either commit. The bus shape is unchanged in this wave; if the hook flags a contract regression, something material drifted — investigate before forcing past.
- **Browser feature-detection collapses to 0% in tests.** If `detectCaptureCapability` returns `ok: false` in EVERY test environment, the hook can never light up — flag it. (Expected: in jsdom under Vitest, `MediaRecorder` is undefined, so the hook test must explicitly stub it. This is normal, not a stop condition.)
- **Working tree shows tracked-file deletions** > 200 lines you didn't author. Run the deletion-check command from `BUILDER-EXECUTION-PLAN.md` BEFORE any analysis.

---

## GH issues to close

| Issue | Closed by |
|---|---|
| [#559](https://github.com/seangalliher/ProbOS/issues/559) | AD-721b-1 commit (`Closes #559`) |
| [#560](https://github.com/seangalliher/ProbOS/issues/560) | AD-721b-2 commit (`Closes #560`) |

[#561](https://github.com/seangalliher/ProbOS/issues/561) (whisper.cpp WASM) **stays open** — it's a separate forward path filed for AD-721b-3, not in scope for this wave.

---

## Acceptance for the wave as a whole

- ✅ Both ADs committed individually, each with `Closes #NNN`.
- ✅ Full Python test gate green at end of wave; baseline + ≥ 10 new tests.
- ✅ Full UI test gate green at end of wave; baseline + ≥ 7 new Vitest tests + 1 regression.
- ✅ AD-734 pre-commit hook never bypassed.
- ✅ `PROGRESS.md` highest-AD line stays at AD-734 (Wave 155 adds two sub-ADs only).
- ✅ `progress-era-5-unification.md` (or current era file) gets one bullet per shipped AD.
- ✅ Both prompt files moved to `prompts/archive/` after wave close (orchestrator handles this).
- ✅ Orchestrator state advanced via `scripts/wave-orchestrator.ps1`.
- ✅ License disposition recorded in both AD entries in `DECISIONS.md`.
- ✅ Operator-facing smoke test instructions in the AD-721b-1 entry (download rhubarb, drop in `tools/rhubarb/`, set `lipsync.backend: "rhubarb"`, restart, send a DM).

---

## Deferrals — explicit forward markers

The following are **explicitly out of scope** for Wave 155:

- **AD-721b-3** — whisper.cpp WASM tiny.en for offline phoneme alignment ([#561](https://github.com/seangalliher/ProbOS/issues/561), already filed). Stays open.
- **AD-721b-2.1** — Server-side ffmpeg transcoding shim (only file if a real operator hits a webm/wav mismatch).
- **AD-721b-2.2** — Browser-side viseme cache by audio_sha256 (defer until profiling shows need).
- **AD-721b-2.3** — Server-streamed TTS path (Coqui / Piper / ElevenLabs). Material architecture change — would obsolete the browser-capture problem entirely. File as a top-level AD if pursued.
- **AD-721b-4** (potential) — rhubarb-lip-sync WASM port for in-browser execution. No maintained WASM port exists today; verify before filing.
- **AD-721b-5** (potential) — server-side viseme cache keyed by audio_sha256.

All deferrals must be tracked with both an AD number AND a GH issue before the wave is closed (per repo memory rule: "Anything deferred in a wave MUST be tracked with both an AD number AND a GitHub issue before the wave is closed"). For Wave 155, all deferrals listed are EITHER already tracked (#561) OR are speculative-only — no new GH issues required at wave-close unless the Builder discovers a concrete need during build.
