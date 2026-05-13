# Wave 156 Dispatch — HXI ergonomics + agent expression

**Date:** 2026-05-13. **Architect:** Sean. **Mode:** Continuous build (one prompt = one commit).
**Theme:** Three small, parallel-safe quality-of-life improvements: one HXI surface gap, one HXI failure-mode polish, one agent-expression capability extension. No cross-AD dependencies between the three prompts.
**Estimated wall-time:** ~5h total (1.5h + 1h + 2h).
**Estimated test count delta:** +12 to +14 (5 Vitest + 7 component + 7 Python — see per-prompt summaries).

---

## Wave goal

Wave 156 closes three Captain-reported quality gaps from the [#527, #558, #612] cluster:

1. **AD-735** ([#527](https://github.com/seangalliher/ProbOS/issues/527)) — Per-agent volume surface. The backend is fully shipped (VoiceProfile.volume since AD-718); the UI never exposed a slider. Captain has no way to lower one chatty agent without muting the bridge.
2. **AD-736** ([#558](https://github.com/seangalliher/ProbOS/issues/558)) — Mic-permission UX polish. The wake-word loop silently dies when the browser blocks the mic or no mic is present; Captain sees nothing actionable.
3. **AD-737** ([#612](https://github.com/seangalliher/ProbOS/issues/612)) — Per-agent custom emotion taxonomy. The v1 fixed 8-emotion set is functional but flat; Counselor cannot reach for "professional concern" distinct from `concerned`.

All three are **internal** code (no external license absorption). All three honour HXI Design Principle #3 (inline SVG, no emoji). All three preserve the AD-731 attachment invariant (no impact on the bus / RPC / attachment paths).

---

## Inputs (read in full before any code)

1. `.github/copilot-instructions.md` — engineering / testing / logging / type-annotation rules. Every commit complies.
2. `prompts/BUILDER-EXECUTION-PLAN.md` — standing rules (test gate, working-tree integrity, log-and-degrade tiers, mic permission BF-276 lesson on PowerShell encoding).
3. `prompts/review-criteria.md` — the standard 3-pass review tiers.
4. The 3 prompt files for this wave:
   - `prompts/ad-718f-per-agent-volume.md` (AD-735)
   - `prompts/ad-705d-mic-permission-ux.md` (AD-736)
   - `prompts/ad-722a-3-emotion-taxonomy.md` (AD-737)
5. Parent context:
   - AD-718 voice profile (shipped Wave 130-ish; voice.ts + crew_profile.VoiceProfile)
   - AD-705 wake-word loop (shipped; wakeWord.ts state machine)
   - AD-722a divergence detector (shipped Wave 143; divergence_detector.py + telemetry.py modulation manifest)
   - AD-722a-7 manifest-driven intent rules (shipped Wave 144)

---

## Standing rules (carry from Wave 155)

- **Test gate (full):** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`. Documented HEAD-flakes (excluded from regression budget): `test_callsign_routing` × 3, `test_ad719_chat_fanout` × 1, `test_ward_room::TestEndorsementActivation::test_browse_threads_sort_recent` × 1, `test_dreaming::TestDreamingIntegration::test_nl_to_dream_cycle_changes_weights` × 1.
- **Per-prompt focused gate (Python):** `pytest tests/test_<adNNN>_*.py -v -n 0`.
- **Per-prompt focused gate (UI):** `cd ui && npx vitest run src/<path>/__tests__/<file>.test.{ts,tsx}`.
- **Working tree:** if you find tracked-file modifications you didn't make, surface them. Do not `git stash` / `git reset --hard`. The 2026-05-08 wipe pattern is documented in `/memories/repo/probos-notes.md`.
- **One commit per AD.** Commit message: `AD-735: <one-line>` / `AD-736: <one-line>` / `AD-737: <one-line>` with `(Wave 156)` suffix and `Closes #NNN`.
- **AD-731 invariant.** None of the three ADs touch the bus, RPC, or attachment paths. If you find yourself reaching for `IntentMessage.params` or `AttachmentStore`, STOP — you've drifted out of scope.
- **AD-734 pre-commit hook.** Wave 156 prompts do NOT touch the chat router, LLM client, or system.yaml — the hook will not fire for these commits. If it DOES fire, something material drifted; investigate before forcing past.
- **NEVER broad-kill python by path** when cleaning up pytest workers. Use `scripts/kill-stale-pytest.ps1`. The 2026-05-12 incident memo is in user memory.
- **PowerShell + UTF-8.** When capturing diagnostic logs to a file (`Out-File`, `tee`, redirection), confirm the BF-276 fix in `__main__.py` is in HEAD; the runtime self-reconfigures stdout encoding so Rich checkmarks don't crash. No `PYTHONIOENCODING=utf-8` workaround needed.

---

## Pre-flight checklist (before drafting Builder dispatch)

Before the Builder starts:

1. **Working-tree integrity.** Run `git diff --numstat | Sort-Object {[int]$_.Split("`t")[1]} -Descending | Select-Object -First 5`. Any tracked file showing >200 deletions = STOP and investigate. (Especially: `crew_profile.py`, `divergence_detector.py`, `telemetry.py`, `cognitive_agent.py`, `wakeWord.ts`, `voice.ts`, `ProfileInfoTab.tsx`.)
2. **Baseline tests.** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` shows the documented HEAD-flake set and nothing else red. UI baseline: `cd ui && npx vitest run` is green.
3. **Highest-AD verification.** Read `PROGRESS.md`. Confirm `AD-734` is the current highest. Wave 156 adds **AD-735, AD-736, AD-737** as new top-level numbers (architect-assigned per the highest-AD audit). State the trio in the build report.
4. **Phantom-API pre-check.** Run `./scripts/phantom-api-precheck.ps1 prompts/ad-718f-per-agent-volume.md prompts/ad-705d-mic-permission-ux.md prompts/ad-722a-3-emotion-taxonomy.md`. Architect ran this at draft time — re-run before build to catch any drift in HEAD since drafting. Expected: 0 phantoms (or all documented as false positives in the prompt body).
5. **Operator action item (FOR THE OPERATOR, NOT THE BUILDER):** to live-smoke AD-735, the operator opens the HXI, picks an agent, and drags the new Volume slider. To live-smoke AD-737, the operator hand-edits a crew seed to add a `custom_emotions:` block (example in `prompts/ad-722a-3-emotion-taxonomy.md` Section 7 step 1). The Builder does NOT seed crew profiles; the test fixtures construct them programmatically.

---

## Build order and dependency DAG

**All three prompts are independent.** No cross-AD dependencies. Build them in any order; recommended order matches the issue-number order for trace-back simplicity:

```
Group A (independent, parallel-safe — but commit serially):
  AD-735  (#527)  ─── UI Volume slider (smallest; warm-up)
  AD-736  (#558)  ─── Mic permission state machine + HXI hint
  AD-737  (#612)  ─── Custom emotion taxonomy + prompt builder rewrite
```

**Commit order: AD-735 → AD-736 → AD-737.** Three commits, one per AD.

A Builder running fully serial can commit them in this order. A Builder running paralleled work-streams can build them concurrently; the commits must still land serially (one PR, three commits, or three PRs in sequence — Architect prefers one consolidated PR for a 5h wave).

---

## Per-prompt summaries

| AD | GH | Files | Tests | Est |
|---|---|---|---|---|
| AD-735 | [#527](https://github.com/seangalliher/ProbOS/issues/527) | `ui/src/components/profile/ProfileInfoTab.tsx` (1 insertion), `ui/src/components/profile/__tests__/ProfileInfoTab.volumeSlider.test.tsx` (new) | ≥ 5 Vitest | 1.5h |
| AD-736 | [#558](https://github.com/seangalliher/ProbOS/issues/558) | `ui/src/audio/wakeWord.ts` (state machine extension), `ui/src/audio/__tests__/wakeWord.micPermission.test.ts` (new), `ui/src/components/MicPermissionHint.tsx` (new), `ui/src/components/__tests__/MicPermissionHint.test.tsx` (new), HXI shell root (1 mount line) | ≥ 5 state-machine Vitest + 2 component | 1h |
| AD-737 | [#612](https://github.com/seangalliher/ProbOS/issues/612) | `src/probos/crew_profile.py` (new dataclass + field), `src/probos/avatars/divergence_detector.py` (custom-name resolution), `src/probos/avatars/telemetry.py` (modulation extension), `src/probos/cognitive/cognitive_agent.py` (prompt builder rewrite), `tests/test_ad737_emotion_taxonomy.py` (new) | ≥ 7 Python | 2h |

---

## License posture

- **No external code absorption.** All three ADs are internal feature work on top of existing ProbOS subsystems.
- **No new dependencies.** `pyproject.toml` and `ui/package.json` are unchanged across all three prompts. Every API used is either repo-internal or a Web/Python platform standard (`navigator.mediaDevices`, `re`, `dataclasses`, `typing`).
- **No `.gitignore` edit.** No new ignore targets.
- **Apache 2.0 propagation only.** Every new file carries the repo's Apache 2.0 posture (matches existing files in the same directory).
- **All-internal confirmed at draft time** by Architect; the License Disposition section in each prompt body restates the confirmation per the wave-154/155 dispatch convention.

---

## Per-commit quality gate

After **each** commit:

1. Run the focused test gate for that AD's tests.
2. Run the full Python test gate. Confirm only documented HEAD-flakes are red.
3. Run the full UI gate (`cd ui && npx vitest run`). Confirm green.
4. Confirm the AD-734 pre-commit hook did NOT fire (none of the wave's commits stage chat router / vision dispatch / system.yaml).
5. Verify `PROGRESS.md` was updated for the AD just shipped (tests count delta + Wave 156 entry).
6. Verify `DECISIONS.md` was appended with the AD closure block.

---

## Hard-stop conditions

Stop the wave and surface to architect immediately if:

- **Phantom API discovered** in any of the three prompts that affects the implementation (not just test fixtures). Specifically: a referenced helper that doesn't exist in the codebase, OR a function signature in the prompt that doesn't match the live signature. (Architect did verify-first at draft time — but HEAD may drift between draft and build; the pre-flight phantom-API pre-check is the canonical re-check.)
- **AD-731 invariant violation** — if any of the three commits accidentally proposes inlining anything into `IntentMessage.params` or bypassing `AttachmentStore`, STOP. None of this wave's scope requires touching the bus.
- **`_REQUIRED_INTENT_EMOTIONS` or `EmotionalIntent` enum modified** by the AD-737 build — the v1 set is FIXED. If a build edit drifts into expanding the manifest, STOP and check Section 6 ("What this does NOT change") in `prompts/ad-722a-3-emotion-taxonomy.md`.
- **`ui/src/audio/modulation_manifest.json` modified** — the manifest is the SHARED vocabulary; custom emotions are per-agent. Any manifest edit is out-of-scope.
- **Emoji introduced into any HXI component** — HXI Design Principle #3 is binding. The Volume slider's speaker glyph and the MicPermissionHint's mic glyph are inline SVG; if a Builder substitutes an emoji "for simplicity", STOP and revert.
- **Test gate regresses past the documented HEAD-flake set.** Any new red test that isn't on the documented list = stop and triage.
- **AD-734 pre-commit hook fires red** unexpectedly. None of this wave's commits should trigger it; if it fires, the staged diff drifted into chat router / LLM client / system.yaml territory — investigate before forcing past.
- **Working tree shows tracked-file deletions** > 200 lines you didn't author. Run the deletion-check command from `BUILDER-EXECUTION-PLAN.md` BEFORE any analysis.

---

## GH issues to close

- [#527](https://github.com/seangalliher/ProbOS/issues/527) — closed by AD-735 commit (per-agent volume slider).
- [#558](https://github.com/seangalliher/ProbOS/issues/558) — closed by AD-736 commit (mic-permission UX).
- [#612](https://github.com/seangalliher/ProbOS/issues/612) — closed by AD-737 commit (custom emotion taxonomy).

Each commit message should include `Closes #NNN` for its corresponding issue.

---

## Post-wave: build report and retrospective

After all three commits land:

1. Write `prompts/build-reports/WAVE-156-BUILD-REPORT.md` summarising:
   - Final test counts before/after wave.
   - Any BFs filed during the wave (none expected).
   - Wall-time taken per AD.
   - Any documented HEAD-flake changes.
2. Update `prompts/wave-orchestrator-state.json`: bump `current_wave` to `157`, `current_stage` to `pending`.
3. Archive the three prompt files to `prompts/archive/`:
   - `prompts/ad-718f-per-agent-volume.md` → `prompts/archive/ad-718f-per-agent-volume.md`
   - `prompts/ad-705d-mic-permission-ux.md` → `prompts/archive/ad-705d-mic-permission-ux.md`
   - `prompts/ad-722a-3-emotion-taxonomy.md` → `prompts/archive/ad-722a-3-emotion-taxonomy.md`
   - Archive this dispatch: `prompts/WAVE-156-DISPATCH.md` → `prompts/archive/WAVE-156-DISPATCH.md`.

---

## Verified at draft time (2026-05-13)

```
Highest AD in DECISIONS.md / decisions-era-5-unification.md: AD-734 (BF-274 chain referenced; AD-734 is the canonical top).
  → AD-735, AD-736, AD-737 are next-three-free (architect-assigned, sequential).

Per-agent voice field (AD-735 backend) already shipped:
  src/probos/crew_profile.py:108           VoiceProfile.volume: float = 0.8
  src/probos/api_models.py:243             SetVoiceProfileRequest.volume
  src/probos/routers/agents.py:236         @router.put("/{agent_id}/voice-profile")
  ui/src/audio/voice.ts:139                utterance.volume = effective.volume ?? 0.8

Mic permission state-machine touch points (AD-736):
  ui/src/audio/wakeWord.ts:32-37           WakeWordState
  ui/src/audio/wakeWord.ts:38-40           WakeFallbackReason (3 reasons; mic_permission_denied is one)
  ui/src/audio/wakeWord.ts:145-150         SR support gate
  ui/src/audio/wakeWord.ts:230-238         onError 'not-allowed' path
  ui/src/audio/wakeWord.ts:463-471         _emitFallbackToast (console.warn only)

Emotion taxonomy v1 (AD-737 parent):
  src/probos/avatars/divergence_detector.py:33-44   EmotionalIntent enum (8 values)
  src/probos/avatars/divergence_detector.py:58-67   INTENT_EXPECTED_RULES
  src/probos/avatars/divergence_detector.py:74-80   INTENT_DIRECTION
  src/probos/avatars/telemetry.py:99-103            _REQUIRED_INTENT_EMOTIONS (manifest validator)
  src/probos/avatars/telemetry.py:184-188           Forward marker: "per-agent palettes are forward marker AD-722a-3"
  src/probos/cognitive/cognitive_agent.py:3175-3196 _build_intent_self_tag_instruction (hardcoded v1 list)

All three prompts conform to AD-731 invariant (no bus / RPC / attachment changes).
All three prompts honour HXI Design Principle #3 (inline SVG; no emoji).
No new dependencies in any prompt (pyproject.toml + ui/package.json unchanged).
```
