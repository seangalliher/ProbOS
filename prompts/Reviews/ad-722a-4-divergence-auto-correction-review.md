# Review: AD-722a-4 — Auto-correction loop on high-magnitude divergence
**Verdict:** ⚠️ Conditional
**The correction-slot lifecycle as drafted clears the entry in the same handler that wrote it — TTS consumer downstream sees nothing.**

## Required (must fix before building)

1. **Slot-clear timing breaks the TTS consumer contract.**
   Section 5 says `DmReplyPipeline.step_7_mark_emitted` clears `runtime.divergence_corrections[agent_id]` immediately after `mark_reply_emitted`. The Solution Overview claims "The TTS endpoint (`POST /api/avatars/tts` per AD-738e-1) reads the corrected modulation when present." TTS is a SEPARATE HTTP call from the browser, made AFTER the DM response returns. With step_7 clearing the slot, TTS will always see `divergence_corrections[agent_id] is None` — the correction never reaches prosody.

   Two options to fix:
   - **(a)** Clear on the NEXT utterance's enter (not exit) — move the `pop(agent_id, None)` to step_1 OR to the pre-LLM `enter_dm` site. Per-utterance budget is enforced via "if there's already an entry for this agent, the budget is exhausted; skip the correction" — checked at write time in Section 3, not at consume time.
   - **(b)** Add a TTL or sequence-number to the correction entry so TTS can claim-and-consume atomically.

   Recommend option (a) — simpler, matches the existing `divergence_results` lifetime (which is also persisted between turns and read by step_8 / TTS).

2. **`compute_divergence` re-call in Section 3's correction branch passes only 2 kwargs but ignores the original `result.match_score` / `result.signed_divergence`.**
   Pseudocode says:
   ```python
   corrected_result = compute_divergence(
       intent_emotion=resolved_v1,
       applied_fired_rules=tuple(corrected_modulation.fired_rules),
   )
   ```
   `compute_divergence` (`divergence_detector.py:287`) IS a 2-arg pure function — that part is correct (verified by reading source). However, the returned `DivergenceResult` will then need `corrected=True` AND `intent_emotion` set back to the custom name (the existing code at line 478 does `dataclasses.replace(result, intent_emotion=intent)` for the same reason). The Section 3 pseudocode does set `corrected=True` via `dataclasses.replace` but does NOT restore the custom-vs-v1 intent name when `resolved_v1 != intent`. **Add the same `if resolved_v1 != intent: result = dataclasses.replace(result, intent_emotion=intent)` step BEFORE the `corrected=True` replace** (or combine into a single `replace`).

3. **`apply_voice_modulation` kwargs addition is the precondition, but the prompt doesn't specify the prosody multiplication site.**
   Section 3 Builder verification step 1 says: "add `noise_scale_factor` / `length_scale_factor` kwargs with default-1.0 no-op." That's correct in shape, but Builder needs to know WHERE in `apply_voice_modulation` to multiply. Telemetry's prosody-emit step likely composes `noise_scale = base_noise * <rule_factors>` somewhere. The kwargs must multiply at the final emit point (after rule_factors apply), otherwise the correction stacks oddly with rule-based prosody. **Add to Section 3: "Builder reads `apply_voice_modulation` body; find the line that finalizes `noise_scale` / `length_scale` on the returned `ModulationSnapshot`, and multiply by the kwargs at that exact site. Document the chosen anchor line in the build report."**

## Recommended

1. **`prior_count` computation in Section 3's pseudocode uses `_agent_id_for_budget` attr that doesn't exist on `DivergenceResult`.** The prompt explicitly tells Builder to replace this with a simpler `corrections.get(agent_id) is None` gate — keep that but DELETE the `prior_count = sum(...)` pseudocode entirely so Builder doesn't get confused into implementing it. Section 3 currently has both forms in the same code block.

2. **DEBUG vs WARNING log levels in test #8.** `test_runtime_without_divergence_corrections_attr_degrades` expects "no exception, log at DEBUG." Per `.github/copilot-instructions.md` standing rule: "Silent failure of an enabled feature is a diagnostic trap. DEBUG is appropriate only for features that are config-disabled." If `auto_correct_enabled=True` but the runtime attr is missing, that's a wiring bug AND an enabled-feature silent failure → WARNING, not DEBUG. Update Section 3's `getattr(runtime, "divergence_corrections", None)` branch and the test expectation.

3. **Forward marker AD-722a-4-1 trigger is fuzzy.** "different emotions need different correction strengths (e.g., concerned miss patterns differ from excited miss patterns)" — quantify: "when divergence-history analytics show >0.15 magnitude variance across emotions for the same correction factor pair over 100+ corrections" or similar. Soft.

4. **Section 4 runtime allocation uses `DivergenceResult` as the type hint** but doesn't import it. Verify the existing runtime.py either imports `DivergenceResult` already (for `divergence_results: dict[str, DivergenceResult]`) or that the new line needs `from probos.avatars.divergence_detector import DivergenceResult` added. Builder should grep; flag in build report.

## Nits

1. `correction_noise_factor: float = 1.15` and `correction_length_factor: float = 0.92` defaults are stated without empirical justification. Add a one-line comment pointing to "matches AD-738e-1's excited delta of +0.15 / -0.08 (verified in `config.py:1068-1075`)" if that's the basis.
2. `auto_correct_threshold: float = 0.6` is 2x the negative threshold (0.3). Document the 2x ratio rationale in the docstring rather than just "higher than negative threshold."

## Verified

- `apply_divergence_check` def line 372 ✅
- `DivergenceResult` frozen at line 140 ✅
- `compute_divergence` 2-arg signature line 287 ✅
- `apply_voice_modulation` at `telemetry.py:399` ✅
- `_resolve_voice_profile_for_intent` at line 336 ✅
- Local variables `snap`, `intent`, `custom_emotions`, `resolved_v1`, `modulation` all exist in `apply_divergence_check` scope at the insertion point (after `div_results[agent_id] = result`).
- AD-727 rule #1 INVERSION justification is documented and the firewall (default-OFF, per-utterance budget, no `response_text` rewrite) matches the standing carve-out pattern.
- No new pip / npm deps. Apache 2.0 internal.
- Cross-prompt dep on AD-726's `step_7_mark_emitted` is acknowledged (Section 5 provides both pipeline-side and inline-fallback paths).

## Build-go criteria

Required findings 1, 2, 3 fixed → re-review for the slot-clear timing fix (this is the architectural pivot; option (a) reshapes step_1 / pre-LLM, not step_7). After re-review, MED risk classification holds; the carve-out from AD-727 rule #1 is narrow enough.


### Re-review (pass-2) — 2026-05-14

**Verdict:** ✅ Approved.

All 3 Required findings from pass-1 are resolved:

1. **Slot-clear timing (CRITICAL)** — moved from step_7_mark_emitted to the START of step_1_sanity_gate_retry (option a). Verified at `prompts/ad-722a-4-divergence-auto-correction.md:220-232`: 5-line prepend block uses getattr(self.ctx.runtime, "divergence_corrections", None) then .pop(self.ctx.agent_id, None). Tier-2 guarded (missing slot benign). Section 3 verification step 3 explicitly forbids the post-emit clear. Pre-seed test renamed 	est_pipeline_step_1_clears_stale_slot (line 246). TTS read window preserved (clear happens at NEXT reply's entry, after TTS has had its chance to consume).
2. **compute_divergence re-call loses custom emotion name** — Section 3 pseudocode now does two dataclasses.replace calls: (a) restore intent_emotion=intent when esolved_v1 != intent (mirrors existing line-478 pattern); (b) set corrected=True. Documented in revision table.
3. **pply_voice_modulation multiplication site** — Section 3 Builder verification step 1 expanded with explicit anchor instruction: locate the LAST write to 
oise_scale / length_scale BEFORE ModulationSnapshot construction, multiply at that site. Builder reports chosen anchor line in build report. Rationale (correction = outermost multiplicative layer, preserves AD-738e-1 stacking) documented.

Cross-prompt collision check with AD-726 step_1: **none**. AD-726 ships the verbatim-moved body of step_1_sanity_gate_retry in eply_pipeline.py; AD-722a-4 prepends BEFORE that body using eplace_string_in_file with SEARCH anchor = "docstring + first line of step_1's verbatim move". AD-726's own SEARCH/REPLACE targets outers/agents.py:1278, not eply_pipeline.py. The two prompts touch different files at different anchors. Dispatch ordering (AD-726 → AD-722a-4) is preserved and documented at line 220.

Pass-1 Recommended #1 (stale prior_count pseudocode with phantom _agent_id_for_budget attr) DELETED. Pass-1 Recommended #2 (DEBUG → WARNING on missing-runtime-attr) flipped to WARNING with structured context per .github/copilot-instructions.md enabled-feature-silent-failure rule; test 8 expectation updated. Pass-1 Recommended #4 (DivergenceResult import in runtime.py) — Section 4 now instructs Builder to grep and add if absent.

No new Required findings. Recommended #3 (quantified forward-marker trigger) and Nits 1-2 left as Builder discretion.

**Risk classification:** MED (unchanged from pass-1 build-go criteria). The AD-727 rule #1 carve-out (prosody-only correction, default OFF, per-utterance budget, esponse_text never rewritten) holds.
