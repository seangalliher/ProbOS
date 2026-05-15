# AD-722a-4 — Auto-correction loop on high-magnitude divergence

**AD:** AD-722a-4. **GH issue closed:** [#613](https://github.com/seangalliher/ProbOS/issues/613).
**Parent ADs:** AD-722a (divergence detector, Wave 143), AD-722a-7 (modulation recompute, Wave 156), AD-737/737a (custom-emotion palette resolution), AD-738e-1 (per-emotion prosody overrides, Wave 158).
**Wave:** 160. **Estimated tests:** +8 pytest. **Estimated wall-time:** ~2.5h. **Risk:** MED — INVERTS the AD-727 rule #1 read-only contract for the auto-correct path; default-OFF mitigates blast radius.

---

## Solution Overview

`apply_divergence_check` (in `src/probos/avatars/divergence_detector.py:372`) is observation-only today: when divergence magnitude exceeds the negative threshold, it fires a trust delta + a Hebbian edge update, but the OUTPUT (`response_text`) ships unchanged. The Captain receives a reply where the agent said "warm" but the voice modulation landed as "neutral" — and there's no second attempt.

AD-722a-4 closes that loop. When `result.magnitude > auto_correct_threshold` (default 0.6 — higher than the negative-fire threshold of 0.3 to avoid retry storms on mild misses), AND the configured budget allows it, the detector flags the result for re-modulation. The DM reply pipeline's existing emotion-resolution step (`step_8_emotion_resolve` per AD-726, OR the inline block at `routers/agents.py:1524..1551` pre-AD-726) consults the flag and, when set, re-invokes `apply_voice_modulation` with adjusted prosody parameters: `noise_scale *= correction_noise_factor`, `length_scale *= correction_length_factor`. The recomputed `DivergenceResult` is stored alongside the original under a new `divergence_corrections` mapping for AD-722c history visibility and for AD-722d Records significance writes.

**The firewall (AD-727 rule #1 carve-out):**
- Auto-correction is **default-OFF** (`avatar_telemetry.auto_correct_enabled: bool = False`). Opt-in only.
- **At most one re-modulation per utterance** (`max_corrections_per_utterance: int = 1`). The detector marks the agent with a per-utterance correction count keyed by `agent_id + reply_id`; the next utterance resets.
- **No retry storm on infrastructure failure.** If the re-modulation call raises, log WARNING and emit the ORIGINAL modulation. Never block the reply.
- **Telemetry-only flag, not output rewrite.** The auto-correction recomputes the MODULATION (prosody parameters consumed by TTS), NOT the `response_text`. The Captain still reads the same words; the voice synthesis applies adjusted prosody. This keeps the carve-out narrow: aesthetic judgment influences delivery, not content.

The TTS endpoint (`POST /api/avatars/tts` per AD-738e-1) reads the corrected modulation when present. Per-emotion prosody overrides from AD-738e-1 apply on top of correction factors (correction is multiplicative on prosody output).

**Slot lifecycle (revised 2026-05-14, Required #1 fix — see Revision section).** The `runtime.divergence_corrections[agent_id]` slot is:
- WRITTEN by `apply_divergence_check` during DM step_6 (divergence check) when the correction fires.
- READ by the TTS endpoint (a SEPARATE HTTP call from the browser, AFTER the DM reply returns).
- CLEARED at the START of the NEXT DM reply, NOT at the end of the current one. Clearing in step_7 of the current reply would race with TTS — the slot would be empty by the time TTS reads it. Clear-on-enter ensures TTS always sees the most-recent correction (or `None` if no correction fired).

The per-utterance budget is enforced AT WRITE TIME via `corrections.get(agent_id) is None` — "if a prior correction for this agent already exists in the slot from this reply, skip." Since step_1 clears the slot at the start of each reply, the first write inside the reply always succeeds; subsequent writes (rare, requires multiple divergence checks in one reply) are blocked.

**Folded:** none.

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `src/probos/config.py` | `AvatarTelemetryConfig` (~line 1025) | Add `auto_correct_enabled`, `auto_correct_threshold`, `max_corrections_per_utterance`, `correction_noise_factor`, `correction_length_factor`. |
| `src/probos/avatars/divergence_detector.py` | `apply_divergence_check` (line 372..end) | Branch after `compute_divergence` returns: when `result.magnitude > threshold` AND budget allows, recompute modulation and write to `runtime.divergence_corrections[agent_id]`. |
| `src/probos/avatars/divergence_detector.py` | `DivergenceResult` (~line 140) | Add `corrected: bool = False` field (default False; backward-compatible). |
| `src/probos/runtime.py` | startup | Allocate `runtime.divergence_corrections: dict[str, DivergenceResult] = {}` next to `runtime.divergence_results`. |
| `tests/test_ad722a4_auto_correction.py` | NEW | 8 boundary tests. |

**Verified anchors:**
- `apply_divergence_check` def: `src/probos/avatars/divergence_detector.py:372` (verified via `grep_search`).
- `DivergenceResult` frozen dataclass: `src/probos/avatars/divergence_detector.py:140` (verified).
- `compute_divergence` returns `DivergenceResult`: `src/probos/avatars/divergence_detector.py:287`.
- `apply_voice_modulation` import surface: `from probos.avatars.telemetry import apply_voice_modulation` (verified line 455 in `apply_divergence_check`).
- `_resolve_voice_profile_for_intent` helper: `src/probos/avatars/divergence_detector.py:336` (verified).
- `AvatarTelemetryConfig.divergence_negative_threshold = 0.3` baseline: `src/probos/config.py:1053`.
- `runtime.divergence_results` allocation site: grep `divergence_results = {}` in `src/probos/runtime.py` (Builder verifies exact line during build).

---

## Section 1 — `AvatarTelemetryConfig` extension

In `src/probos/config.py` `AvatarTelemetryConfig` (around line 1025), append the new fields AFTER the existing `divergence_aggregate_window: int = 50` field and BEFORE the AD-722c history block. The Pydantic model is NOT frozen; field-ordering discipline does not apply.

```python
    # AD-722a-4: auto-correction loop on high-magnitude divergence.
    # Default OFF — INVERTS the AD-727 rule #1 read-only contract for the
    # MODULATION path (aesthetic judgment influences prosody output).
    # Carve-out is intentionally narrow: re-modulation does NOT rewrite
    # response_text; only the prosody parameters consumed by TTS change.
    auto_correct_enabled: bool = False
    # Magnitude above which a re-modulation attempt fires. Higher than
    # divergence_negative_threshold (0.3) to avoid retry storms on mild
    # misses. Operator can tune downward at their own risk.
    auto_correct_threshold: float = 0.6
    # Per-utterance budget. Set to 0 to disable corrections without flipping
    # auto_correct_enabled (useful for A/B comparison runs).
    max_corrections_per_utterance: int = 1
    # Multiplicative factor applied to Piper noise_scale during correction.
    # Higher noise = more prosodic variation; correction nudges TOWARD the
    # intended emotion's expressive profile (verified by AD-738e-1 deltas).
    correction_noise_factor: float = 1.15
    # Multiplicative factor applied to Piper length_scale during correction.
    # Lower length = faster speech; correction profile mirrors AD-738e-1's
    # excited (faster) vs. concerned (slower) intent direction.
    correction_length_factor: float = 0.92
```

## Section 2 — `DivergenceResult` gains `corrected` field

`DivergenceResult` is frozen — field-ordering rule applies. Add `corrected: bool = False` at the END of the field list. Update `to_dict()` to include the new field.

In `src/probos/avatars/divergence_detector.py` around line 140-170 (the `class DivergenceResult` block), Builder reads the full dataclass first, then appends the field at the end of the field list (after `magnitude: float`), keeping all existing field-ordering intact.

```python
@dataclass(frozen=True)
class DivergenceResult:
    # ... existing fields unchanged ...
    intent_emotion: str
    applied_fired_rules: tuple[str, ...]
    match_score: float
    signed_divergence: float
    magnitude: float
    # AD-722a-4: True when this result is the post-correction recompute.
    # The pre-correction result is preserved in runtime.divergence_results;
    # the post-correction is stored in runtime.divergence_corrections.
    corrected: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "intent_emotion": self.intent_emotion,
            "applied_fired_rules": list(self.applied_fired_rules),
            "match_score": self.match_score,
            "signed_divergence": self.signed_divergence,
            "magnitude": self.magnitude,
            "corrected": self.corrected,
        }
```

## Section 3 — `apply_divergence_check` correction branch

The existing function already stores the original result on `runtime.divergence_results[agent_id]` (verified around line 478 of `divergence_detector.py`). Add a correction branch IMMEDIATELY AFTER that store and BEFORE the AD-722a-5 ring-buffer append. Builder reads the full function body first to find the exact insertion line.

Pseudocode for the new branch (Builder writes this as a clean append, NOT a multi_replace adjacent to other AD blocks — BF-274):

```python
    # AD-722a-4: auto-correction on high-magnitude divergence. Tier-2
    # internally — re-modulation failure logs WARNING and leaves the
    # original modulation untouched; never blocks a reply.
    if (
        getattr(t_cfg, "auto_correct_enabled", False)
        and result.magnitude > getattr(t_cfg, "auto_correct_threshold", 0.6)
    ):
        corrections = getattr(runtime, "divergence_corrections", None)
        if corrections is None:
            # Wiring bug: feature is enabled but the runtime slot is missing.
            # WARNING (not DEBUG) per .github/copilot-instructions.md standing
            # rule — silent failure of an enabled feature is a diagnostic trap.
            logger.warning(
                "AD-722a-4: auto_correct_enabled=True but "
                "runtime.divergence_corrections is missing for agent=%s; "
                "correction skipped (allocate the slot in runtime.py startup)",
                agent_id,
            )
        else:
            budget = getattr(t_cfg, "max_corrections_per_utterance", 1)
            # Per-utterance budget: the DM reply pipeline's step_1 clears
            # the slot at the start of each reply. If the slot is empty,
            # this is the first correction this utterance — fire. If it's
            # populated, a prior correction already fired in this reply;
            # skip (single-entry-per-utterance budget for v1).
            if budget > 0 and corrections.get(agent_id) is None:
                try:
                    from probos.avatars.telemetry import apply_voice_modulation
                    voice_profile = _resolve_voice_profile_for_intent(runtime, agent_id)
                    signals = getattr(snap, "current_signals", None)
                    if signals is not None:
                        corrected_modulation = apply_voice_modulation(
                            voice_profile, signals, intent=intent,
                            custom_emotions=custom_emotions,
                            noise_scale_factor=getattr(t_cfg, "correction_noise_factor", 1.15),
                            length_scale_factor=getattr(t_cfg, "correction_length_factor", 0.92),
                        )
                        corrected_result = compute_divergence(
                            intent_emotion=resolved_v1,
                            applied_fired_rules=tuple(corrected_modulation.fired_rules),
                        )
                        # Mirror the line-478 pattern: restore the custom
                        # emotion name when ``resolved_v1`` differs from
                        # the operator-facing ``intent`` (otherwise downstream
                        # records would show the v1-resolved fallback name
                        # instead of the original custom emotion).
                        if resolved_v1 != intent:
                            corrected_result = dataclasses.replace(
                                corrected_result, intent_emotion=intent,
                            )
                        corrected_result = dataclasses.replace(
                            corrected_result, corrected=True,
                        )
                        corrections[agent_id] = corrected_result
                        logger.info(
                            "AD-722a-4: auto-correction applied for agent=%s "
                            "intent=%s pre_magnitude=%.3f post_magnitude=%.3f",
                            agent_id, intent, result.magnitude,
                            corrected_result.magnitude,
                        )
                except Exception:
                    logger.warning(
                        "AD-722a-4: re-modulation raised for agent=%s; "
                        "shipping original modulation",
                        agent_id, exc_info=True,
                    )
```

**Builder verification before SEARCH/REPLACE:**

1. Confirm `apply_voice_modulation` accepts `noise_scale_factor` / `length_scale_factor` kwargs. If it does NOT (verified by reading `src/probos/avatars/telemetry.py:399` — `def apply_voice_modulation`), Builder MUST add those kwargs with default-1.0 no-op. **Multiplication site (REQUIRED, per pass-1 Required #3):**
   - Builder reads the body of `apply_voice_modulation` end-to-end and locates the line(s) that FINALIZE `noise_scale` / `length_scale` on the returned `ModulationSnapshot` (i.e., AFTER the rule-based prosody factors have been composed; this is the LAST write to those fields before the `ModulationSnapshot` is constructed and returned).
   - At that exact site, multiply: `noise_scale *= noise_scale_factor`, `length_scale *= length_scale_factor`.
   - Multiplying BEFORE rule-factor composition would make the correction stack oddly with AD-738e-1 per-emotion overrides; multiplying AFTER preserves the AD-738e-1 contract (correction is the outermost multiplicative layer).
   - Builder documents the chosen anchor line in the build report so reviewers can verify the choice. Default kwargs are `1.0` — existing callers see a perfect no-op.
2. The `corrections.get(agent_id) is None` gate is the budget check. No per-history-scan needed; the slot is cleared at the start of each reply by `DmReplyPipeline.step_1_sanity_gate_retry` (see Section 5), so single-entry-per-utterance is enforced by the lifecycle.
3. **DO NOT clear `runtime.divergence_corrections[agent_id]` after `mark_reply_emitted()`.** The TTS endpoint reads the slot AFTER the DM reply returns; clearing post-emit would race TTS to empty. Slot-clear lives at the START of the NEXT reply (Section 5).
4. Builder confirms `DivergenceResult` is imported at module top of `divergence_detector.py` (it's the file that DEFINES the class, so `dataclasses.replace` works directly on the in-scope class; no new import needed).

## Section 4 — Runtime allocation

In `src/probos/runtime.py`, find the existing `divergence_results = {}` allocation (Builder greps to confirm exact line) and add a sibling line immediately after:

```python
        # AD-722a-4: post-correction results. Populated by
        # apply_divergence_check when auto_correct_enabled and the
        # original result's magnitude exceeded auto_correct_threshold.
        # Cleared at the START of the NEXT DM reply by
        # DmReplyPipeline.step_1_sanity_gate_retry (NOT at step_7;
        # TTS reads the slot AFTER the reply returns).
        self.divergence_corrections: dict[str, DivergenceResult] = {}
```

If `DivergenceResult` is not already imported at the top of `runtime.py` (Builder greps to confirm; AD-722a-era code may already import it for the `divergence_results: dict[str, DivergenceResult]` annotation), add `from probos.avatars.divergence_detector import DivergenceResult` to the import block.

## Section 5 — DM reply pipeline clears the slot AT REPLY ENTRY (option a, revised 2026-05-14)

**Revision rationale (pass-1 Required #1 fix):** Pass-1 review flagged that clearing in `step_7_mark_emitted` runs BEFORE TTS reads the slot. The TTS endpoint (`POST /api/avatars/tts`) is a separate HTTP call from the browser, dispatched AFTER the DM reply returns. With a step_7 clear, TTS always sees `None` and the correction is dead-on-arrival. Option (a) (clear at reply-entry, NOT exit) was chosen over option (b) (TTL/sequence) because it's simpler, requires no atomic claim-and-consume primitive, and matches the existing `divergence_results` slot lifecycle (which is also persisted between turns and read by step_8 / TTS).

AD-726 lands BEFORE this AD per Wave 160 dispatch ordering. Builder appends the following block at the START of `DmReplyPipeline.step_1_sanity_gate_retry` (i.e., the FIRST statement inside the method body, BEFORE the verbatim-moved sanity-gate code from AD-726):

```python
        # AD-722a-4: clear the per-utterance correction slot from the
        # PRIOR reply. TTS has had its chance to read it between the
        # prior reply's return and this new reply's arrival. Clearing
        # here — not in step_7 — keeps the slot populated through the
        # TTS read window. Tier-2 guarded: missing slot is benign.
        _corrections = getattr(self.ctx.runtime, "divergence_corrections", None)
        if _corrections is not None:
            _corrections.pop(self.ctx.agent_id, None)
```

This block is added by `replace_string_in_file` on `src/probos/cognitive/dm/reply_pipeline.py` — the SEARCH anchor is the docstring + first line of `step_1_sanity_gate_retry`'s verbatim move (AD-726 ships the method body; AD-722a-4 prepends this 5-line guard). Builder reads AD-726's post-build state of `reply_pipeline.py` to confirm the SEARCH anchor before inserting.

No modification to `routers/agents.py` is needed for the slot-clear — the pipeline owns the lifecycle.

## Section 6 — Test plan

`tests/test_ad722a4_auto_correction.py` — 8 boundary tests:

1. `test_default_off_does_not_correct` — `auto_correct_enabled=False` ⇒ no `divergence_corrections` entry written even for `magnitude=1.0`.
2. `test_threshold_gate_below_does_not_fire` — `magnitude=0.5`, threshold `0.6` ⇒ no correction.
3. `test_threshold_gate_above_fires` — `magnitude=0.7`, threshold `0.6` ⇒ `runtime.divergence_corrections[agent_id]` populated with `corrected=True`.
4. `test_budget_exhausted_skips_second_correction` — call detector twice without a mark_reply_emitted intervening ⇒ second call does NOT overwrite (single-entry-per-utterance budget).
5. `test_remodulation_exception_logs_and_degrades` — `apply_voice_modulation` raises ⇒ correction NOT written, original `divergence_results[agent_id]` intact, no exception bubbles.
6. `test_pipeline_step_1_clears_stale_slot` — pre-seed `runtime.divergence_corrections[agent_id]` with a result from a prior reply; call `step_1_sanity_gate_retry` ⇒ slot is empty afterward. (Renamed from `test_pipeline_step_clears_slot`; verifies the option-(a) lifecycle.)
7. `test_correction_result_serializes_corrected_field` — `DivergenceResult.to_dict()` includes `"corrected": True`.
8. `test_runtime_without_divergence_corrections_attr_degrades` — `delattr(runtime, "divergence_corrections")` ⇒ correction branch logs WARNING (per `.github/copilot-instructions.md` standing rule: silent failure of an enabled feature is a diagnostic trap; WARNING not DEBUG when `auto_correct_enabled=True` and the slot is missing) and returns; no exception bubbles.

Use `_FakeRuntime` / `_FakeAgent` stub pattern (see `tests/test_ad722a_divergence_detector.py:497`).

---

## What This Does NOT Change

- `response_text` is NEVER rewritten by the correction (only modulation parameters).
- `divergence_results[agent_id]` (the pre-correction result) is preserved. AD-722c history continues to record the ORIGINAL divergence; AD-722d significance writes see both.
- `apply_voice_modulation` callers other than `apply_divergence_check` are unchanged (default-1.0 kwargs preserve no-op behavior).
- AD-727 rule #1's broader read-only contract remains for vision-vs-model paths. This AD's carve-out is scoped to the MODULATION path only.
- AD-731 invariant.

---

## Verification Commands

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad722a4_auto_correction.py -v -n 0 | Select-Object -Last 25
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad722a_divergence_detector.py tests/test_ad737_emotion_taxonomy.py tests/test_ad738e1_prosody_overrides.py -v -n 0 | Select-Object -Last 30
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile | Select-Object -Last 3
```

No UI files modified — `npm run build` not required.

---

## Tracker Updates

- **PROGRESS.md:** add `AD-722a-4 — Auto-correction loop on high-magnitude divergence (+8 pytest tests; closes #613). Default OFF. Re-modulates prosody only — response_text never rewritten. Per-utterance budget (1 correction). DivergenceResult gains corrected: bool field. runtime.divergence_corrections sibling map populated by apply_divergence_check, cleared at reply-entry by DmReplyPipeline.step_1_sanity_gate_retry (NOT step_7 — TTS reads slot post-reply).`
- **docs/development/roadmap.md:** remove #613 row; add forward markers AD-722a-4-1 (per-emotion correction factors instead of global), AD-722a-4-2 (multi-utterance learning: correction history feeds into the next emotion's baseline prosody).
- **DECISIONS.md:** append `### AD-722a-4 — Auto-correction loop` with the firewall paragraph from Solution Overview.

---

## License Disposition

All-internal Apache 2.0. No new deps.

---

## Forward markers (technical-trigger language)

- **AD-722a-4-1 — Per-emotion correction factors.** Advances when divergence-history analytics show different emotions need different correction strengths (e.g., "concerned" miss patterns differ from "excited" miss patterns).
- **AD-722a-4-2 — Multi-utterance correction learning.** Advances when correction success rate (post-correction magnitude < pre-correction magnitude) is stable above 60% for 100+ corrections, OR when a deployment needs adaptive correction baselines that drift toward observed agent prosody.

---

## Acceptance Criteria

- ✅ Config fields added; `AvatarTelemetryConfig()` still constructs with zero args.
- ✅ `DivergenceResult.corrected` field defaults `False`; existing serializations preserve schema (add the key but never break older readers that ignore unknown fields).
- ✅ `apply_divergence_check` correction branch fires only when both gates pass.
- ✅ 8 new tests pass; existing `tests/test_ad722a_*.py` tests stay green UNCHANGED.
- ✅ Full gate green.
- ✅ Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-14)

```
apply_divergence_check def:
  src/probos/avatars/divergence_detector.py:372: def apply_divergence_check(
DivergenceResult class:
  src/probos/avatars/divergence_detector.py:140: class DivergenceResult:
compute_divergence:
  src/probos/avatars/divergence_detector.py:287: def compute_divergence(
apply_voice_modulation:
  src/probos/avatars/telemetry.py:399: def apply_voice_modulation(
AvatarTelemetryConfig + divergence_detection:
  src/probos/config.py:1025: class AvatarTelemetryConfig(BaseModel):
  src/probos/config.py:1052: divergence_detection: bool = False
divergence_negative_threshold baseline:
  src/probos/config.py:1053 (Builder confirms the value 0.3)
runtime.divergence_results allocation:
  (Builder greps src/probos/runtime.py for "divergence_results" to confirm exact line.)
```

---

## Revision (2026-05-14)

Pass-1 review (`prompts/Reviews/ad-722a-4-divergence-auto-correction-review.md`) raised 3 Required findings + 4 Recommended. Revision addresses all 3 Required and 3 of the 4 Recommended (#1 stale prior_count pseudocode; #2 DEBUG\u2192WARNING for missing-runtime-attr; #4 DivergenceResult import note). Recommended #3 (quantified AD-722a-4-1 trigger) absorbed inline.

| # | Finding | Resolution |
|---|---|---|
| Required 1 (CRITICAL) | Slot-clear in step_7 races TTS to empty \u2014 feature dead-on-arrival | Slot-clear MOVED from `step_7_mark_emitted` to the START of `step_1_sanity_gate_retry`. Section 5 fully rewritten with option (a) rationale. Pre-seed test renamed `test_pipeline_step_1_clears_stale_slot`. Section 3 verification step 3 explicitly forbids the post-emit clear. Solution Overview gains a "Slot lifecycle" subsection documenting the WRITE / READ / CLEAR points. Tracker line updated to reflect the new lifecycle. |
| Required 2 | `compute_divergence` re-call loses custom emotion name when `resolved_v1 != intent` | Pseudocode in Section 3 now does TWO `dataclasses.replace` calls: first to restore `intent_emotion=intent` (only when `resolved_v1 != intent`, mirroring the existing line-478 pattern), second to set `corrected=True`. Combined as two replace calls rather than one for clarity. |
| Required 3 | `apply_voice_modulation` kwargs added but multiplication site unspecified | Section 3 Builder verification step 1 expanded with explicit multiplication-site instruction: locate the LAST write to `noise_scale` / `length_scale` BEFORE `ModulationSnapshot` construction; multiply at that site. Rationale (correction = outermost multiplicative layer, preserves AD-738e-1 stacking) documented. Builder reports chosen anchor line in build report. |
| Recommended 1 | `prior_count` pseudocode with phantom `_agent_id_for_budget` attr | DELETED. Section 3 pseudocode now uses `corrections.get(agent_id) is None` directly with a comment explaining the lifecycle. |
| Recommended 2 | DEBUG vs WARNING on missing-runtime-attr | Changed to WARNING. Pseudocode in Section 3 now emits a WARNING with structured context ("auto_correct_enabled=True but runtime.divergence_corrections is missing; allocate the slot in runtime.py startup"). Test 8 expectation updated. |
| Recommended 4 | `DivergenceResult` import in runtime.py unverified | Section 4 now instructs Builder to grep `runtime.py` for `DivergenceResult` and add `from probos.avatars.divergence_detector import DivergenceResult` to imports if absent. |

**Out-of-scope for this revision** (deferred per "no scope expansion" rule):

- Recommended #3 (quantified AD-722a-4-1 forward-marker trigger) \u2014 the existing trigger phrasing is qualitative; quantifying it precisely requires divergence-history analytics that don't exist yet. Left as-is.
- Nits 1-2 (correction-factor empirical justification; 2x ratio rationale) \u2014 left to Builder discretion via inline comments.

**Cross-prompt coordination (Required #1 fix \u2014 lifetime contract change):**

The slot-clear move from step_7 to step_1 changes the cross-prompt seam with AD-726:
- BEFORE (pass-1): AD-722a-4 appended to AD-726's `step_7_mark_emitted` (verbatim-moved code).
- AFTER (pass-2): AD-722a-4 prepends a 5-line guard to AD-726's `step_1_sanity_gate_retry` (verbatim-moved code).

Both sides preserve the verbatim-move discipline of AD-726 \u2014 the prepend is BEFORE the moved body; no edit to the moved code itself. No collision with AD-726's pass-2 revisions (which add `params` / `message_text` to ctx + drop `sanity_result` from ctx \u2014 orthogonal changes). The seam is documented in AD-726's pass-2 Revision section as well.
