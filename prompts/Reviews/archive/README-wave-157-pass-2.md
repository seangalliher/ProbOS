# Wave 157 — Pass 2 Sweep Summary

**Date:** 2026-05-13
**Reviewer:** Architect (Copilot)
**Prompts in wave:** 1 — `ad-721b-2-3-server-streamed-tts.md` (AD-738)
**Pass-1 verdict:** ⚠️ Conditional (3 Required findings)
**Pass-2 verdict:** ✅ **Approved — all Required resolved, no new findings**
**Wave verdict:** ✅ **APPROVED — ADVANCE to GATE 1**

---

## Per-prompt verdicts

| Prompt | Pass-1 | Pass-2 | One-line justification |
|---|---|---|---|
| AD-738 — Server-streamed TTS via Piper | ⚠️ Conditional | ✅ Approved | All 3 Required fixes verified against live codebase; 4 of 6 Recommended folded; 2 deferred with explicit rationale; no new findings. |

---

## Required findings closure

| # | Pass-1 Required | Resolution | Verification |
|---|----------------|------------|--------------|
| R1 | Phantom `AttachmentStore.put(...)` | Replaced with canonical `hashlib.sha256(...).hexdigest()` + `await store.write(hash, blob, mime)` mirroring `chat.py:665-692` | `grep "store\.put\("` → 0 hits in code or prose; `grep "store\.write\("` → 3 code-block hits, all matching live Protocol signature |
| R2 | Default-config HTTP regression | Added `GET /api/avatars/tts/status` endpoint + `_fetchTtsStatus` module-level cache + `_invalidateTtsStatus` on POST failure; load-bearing Vitest asserts ZERO POST when probe returns `backend=browser` | Section 5b row 1 explicit assertion: "fetch was called exactly ONCE total (the GET probe), speechSynthesis.speak called 3 times, NO POST to /api/avatars/tts" |
| R3 | Section 2e canonical block had `--output_raw -` (wrong) | Replaced canonical block with `--output_file -`; removed duplicated correction-in-prose paragraph; class docstring documents the `--output_raw` pitfall and cites rhasspy/piper README archive 2025-10-06 | `grep "--output_raw"` → 7 hits, all in PROSE (warnings, revision notes); 0 in code blocks. `grep "--output_file"` confirms canonical block uses `"--output_file", "-"` |

---

## Recommended findings disposition

| # | Pass-1 Recommended | Disposition | Acceptable? |
|---|--------------------|-------------|-------------|
| 1 | `agent_id` unused in body | Folded — body is `{text}` only | ✅ |
| 2 | useLipSyncCapture dual-fire on capture path | Deferred — documented as follow-up | ✅ Out-of-scope; capture path returns null today, only one wasted MediaRecorder spin per OPT-IN piper utterance |
| 3 | Cancel in-flight `<audio>` on second call | Folded — `_activeAudio` ref + Vitest test | ✅ |
| 4 | `select_backend(config: object)` typing | Folded — typed as `TTSConfig` via TYPE_CHECKING | ✅ |
| 5 | `voice_model_dir` configurable field | Deferred — repo-rooted default documented | ✅ Out-of-scope; mild scope expansion |
| 6 | Server-side default-config no-op test | Folded into tightened `test_endpoint_tts_browser_backend_returns_disabled` | ✅ |

---

## New findings introduced by revision

**None.** The revision is surgical: three targeted Section 4a / Section 3 / Section 2e edits, plus four new Python tests, three new Vitest tests, one new Captain decision (#9), one new endpoint, and a Revision section documenting the changes. No collateral edits to other sections beyond consistent terminology updates ("write" replacing "put" in prose at L924 / L1088 / L53 / L559 / L564).

Cosmetic carryover: the Verified Against Codebase footer at L1140 still cites `config.py:1140` for `audio/wav` instead of the actual `filesystem_store.py:38` (pass-1 Nit #2). Non-blocking.

---

## Highest-risk areas — pass-2 status

| Area | Pass-1 risk | Pass-2 status |
|---|---|---|
| Section 3 endpoint write-side (phantom API) | ❌ AttributeError on first integration test | ✅ Mirrors chat.py:665-692 verbatim |
| Section 4a default-config behaviour | ❌ Performance regression on every utterance | ✅ Probe + cache + load-bearing test asserting zero-POST |
| Section 2e implementation correctness | ❌ Builder copy-paste of wrong block | ✅ Single canonical block with correct `--output_file -`; corrective prose demoted to docstring NOTE |

---

## Internal consistency

- Solution Overview (5 pieces) — consistent with Files-to-Modify and Section 0.
- Captain decision #5 references decision #9 + Section 4a — consistent with implementation.
- Captain decision #9 (zero-HTTP guarantee) referenced in Section 4a code comment AND Acceptance criterion #1.
- Test count: header says ≥ 18 (≥ 13 Python + ≥ 5 Vitest); Section 5a lists 21 Python tests, 5b lists 6 Vitest, 5c lists 1 regression. Total 28, comfortably above floor.
- `.gitignore` line 3 verification preserved.
- Highest-AD numbering verified (AD-737 → AD-738; forward markers AD-738a/b/c/d).

---

## Builder dispatch posture

**ADVANCE to GATE 1.** The pre-flight items in `WAVE-157-DISPATCH.md` are satisfied by the verified codebase footer and pass-2 self-checks documented in the Revision section. Builder may proceed to AD-738 implementation.

**Pre-flight reminder for the Builder:**

1. Run `./scripts/phantom-api-precheck.ps1 prompts/ad-721b-2-3-server-streamed-tts.md` — expected zero phantoms.
2. Run focused Python gate `pytest tests/test_ad738_piper_tts.py -v -n 0` after Section 3 lands.
3. Run focused UI gate `cd ui; npx vitest run src/audio/__tests__/voice.serverTts.test.ts src/audio/__tests__/useLipSyncCapture.test.tsx` after Section 4 lands.
4. Cross-platform stub-binary pattern from `tests/test_ad721b1_rhubarb_backend.py` is the verified template for piper subprocess stubs.

---

## Process notes for Wave 157 / Wave 158

- **Pre-flight question shape upgrade:** Pass-1's pre-flight item 6 framed the AttachmentStore audit as "verify mime is keyword-acceptable" — the deeper question (and the actual defect) was "does the method exist at all?" Update the Wave 158 pre-flight template to ask the **method-name** check before the **kwarg-shape** check. This is the third recurrence of the method-shape phantom class (TrustNetwork → Procedure → WorkItemStore.add → AttachmentStore.put per user-memory note).

- **Default-config invariant testing:** Captain decision #9's load-bearing Vitest ("ZERO POST when status reports backend=browser") is the right shape for any future "operator-opts-in" feature: assert the contract directly with a count assertion, not just an outcome assertion. Add to the AD-template-for-feature-flags playbook.

- **Code-block-vs-prose discipline (BF-274 / BF-278 lineage):** The pass-1 R3 finding caught a textbook BF-274 footgun shape. The revision's removal of the standalone correction paragraph + folding into the canonical block + docstring NOTE is the canonical fix. Future prompt reviews should treat "code in body, correction in prose" as an automatic Required.

---

## Final wave verdict

**✅ APPROVED — Wave 157 cleared for Builder execution.**

Single prompt, all three Required findings resolved with verified code-level fixes. Recommended dispositions are honest (folded vs. deferred-with-rationale). The revision section is auditable and accurate. Convention #15 (relaxed: 1 prompt with no ⚠️ tolerance since highest-risk and only-prompt are the same) is satisfied — the only prompt is ✅, so the wave is ✅.

**Recommendation: ADVANCE to GATE 1.** Do NOT reset to revision.
