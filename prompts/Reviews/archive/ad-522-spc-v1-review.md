# Review: AD-522 v1 — SPC Calibration Profile + Western Electric Rules
**Verdict:** ✅ Approved
**Scope is honestly bounded; statistics correct; all four WE rules canonical; no field-name collision.**

---

## Required (must fix before building)

_None._

## Recommended

1. **Section 6 wiring lacks an explicit insertion point.** The prompt says "Sync `_wire_spc_calibration` mirroring AD-525/AD-530 pattern" but provides no SEARCH/REPLACE block. Builder will have to choose where in `src/probos/startup/finalize.py` to (a) define the function and (b) call it from the dispatch list at line 339+. Recommend adding a SEARCH/REPLACE that anchors on `_wire_gap_remediation_tracker` (line 122) for the function definition and on `if _wire_gap_remediation_tracker(runtime=runtime, config=config):` (line 345) for the dispatch call. Mirroring AD-539c is closer than AD-525/AD-530 because AD-539c's pattern uses the boolean return + `if _wire_…(…):` dispatch shape that's now standard.

2. **Section 5 wiring lacks insertion point in `config.py`.** SystemConfig has 100+ fields (lines 1837–1949). Recommend a SEARCH/REPLACE anchored on the AD-487 line:
   ```
   self_distillation: SelfDistillationConfig = SelfDistillationConfig()  # AD-487
   ```
   becomes:
   ```
   self_distillation: SelfDistillationConfig = SelfDistillationConfig()  # AD-487
   spc: SPCConfig = Field(default_factory=SPCConfig)  # AD-522 v1
   ```
   And the `SPCConfig` class definition itself needs an insertion-point anchor too (anchor on `class SystemConfig(BaseModel):` line 1837 — insert immediately above).

3. **Dependencies header contradicts "What This Does NOT Change".** Header line 6 reads `EmergentDetector (consumed read-only)`. The NOT-Change section says `EmergentDetector — read-only (no integration in v1; AD-522c integrates SPC zones into Graduated Response).` These are mutually inconsistent — v1 either consumes EmergentDetector or it doesn't. Per the body's intent, it does NOT. Fix the dependencies header to:
   ```
   - Depends on: crew_profile.PersonalityTraits (read-only); stdlib statistics only.
   ```
   And remove the EmergentDetector line. (PersonalityTraits is also "noted as read-only consumer" but the v1 doesn't actually consume it — `sigma_multiplier` is a constructor default with no neuroticism wiring. The body acknowledges this is deferred to AD-522d. So PersonalityTraits is noted-only too. Fix the wording to reflect "future-consumer" rather than "read-only consumer".)

## Nits

1. **Section 2 `__post_init__` first branch is unreachable.** `field(default_factory=deque)` always returns a `deque`, so `if not isinstance(self._samples, deque)` will never trigger. The `elif self._samples.maxlen != self.sample_window` branch handles the maxlen rebind correctly. The first branch is dead defensive code. Either remove it or collapse to a single rebind:
   ```python
   def __post_init__(self) -> None:
       if not isinstance(self._samples, deque) or self._samples.maxlen != self.sample_window:
           self._samples = deque(self._samples or (), maxlen=self.sample_window)
   ```

2. **Section 3 Rules 2/3 — add a code comment documenting the "same-side" implicit guarantee.** The `above_Nsigma >= K or below_Nsigma >= K` check correctly enforces "same side" because mutual exclusion at >2σ is automatic (a 3-sample window cannot have ≥2 above-2σ AND ≥2 below-2σ simultaneously; same for 4-of-5). Future readers will second-guess this. One-line comment:
   ```python
   # Rule 2: 2-of-3 same side >2σ. The OR is correct: a 3-sample window can't
   # have both above_2sigma>=2 AND below_2sigma>=2 (would require 4+ samples).
   ```

3. **Test 6 "Statistics computation" is broad.** Recommend splitting into two tests: `test_calibration_profile_mean_stdev_computed` and `test_calibration_profile_ucl_lcl_at_three_sigma`. Either way Builder can implement, but an explicit UCL/LCL test pins the 3σ choice in the test name.

## Verified

- **Pre-deferral honesty.** v1 scope is honestly 2 of 5: AgentCalibrationProfile + WesternElectricRules.check (4 of 8 rules). No Cp/Cpk indices, no EmergentDetector wiring, no moving-range chart, no Holodeck calibration, no AD-503/504 Counselor consumption smuggled in. Body and "What This Does NOT Change" are aligned (modulo Recommended #3 wording fix). ✅
- **Statistics formula correctness.** `UCL = mean + 3σ`, `LCL = mean - 3σ` — canonical Shewhart 3σ control limits. `statistics.fmean` (float-fast) and `statistics.stdev` (sample stdev, n-1 denominator) are appropriate stdlib choices. ✅
- **Western Electric Rule 1 (1 point beyond 3σ):** `abs(v - mean) > 3.0 * stdev` — canonical. ✅
- **Western Electric Rule 2 (2-of-3 in Zone A, same side):** `above_2sigma >= 2 or below_2sigma >= 2` — correct (mutual-exclusion guarantee in a 3-sample window). ✅
- **Western Electric Rule 3 (4-of-5 in Zone B, same side):** `above_1sigma >= 4 or below_1sigma >= 4` — correct (same mutual-exclusion guarantee in 5-sample window). ✅
- **Western Electric Rule 4 (8 consecutive same side of centerline):** `all_above` OR `all_below` against `mean` — canonical. ✅
- **Defensive thresholds.** `WesternElectricRules.check` early-returns `[]` when `profile.sample_count < 8 OR profile.stdev == 0.0`. Both conditions present, both correct, both before any windowing. ✅
- **`AgentCalibrationProfile.zone()` defensive.** Returns `"unknown"` when `sample_count < 2 OR stdev == 0.0`. ✅
- **Pre-check FPs documented.** All 3 (`runtime.spc_calibration_store`, `SystemConfig.spc`, `WesternElectricRules.check(window_size=)`) are introduced by the prompt itself — convention #1 (Wave 5) and convention #5 (kwarg-collision FP). Not real findings. ✅
- **Pydantic field name `spc` does not collide.** SystemConfig grep (lines 1837–1949) shows no existing `spc` field; closest neighbors are `self_distillation`, `naval_organization`, `creative_expression`. ✅
- **EventType `SPC_RULE_VIOLATED` does not exist yet.** `grep -rn "SPC_RULE_VIOLATED" src/probos/` returns 0 hits. Section 0 introduces it cleanly. ✅
- **`runtime.spc_calibration_store` does not exist yet.** `grep -rn "spc_calibration_store" src/probos/` returns 0 hits. Section 4 introduces it. ✅
- **Wiring pattern matches existing AD-525/AD-530/AD-539c shape.** `_wire_creative_expression` (finalize.py:80), `_wire_classification_gate` (finalize.py:105), `_wire_gap_remediation_tracker` (finalize.py:122) all use `(*, runtime: Any, config: "SystemConfig") -> bool` signature with dispatch via `if _wire_…(…):` at lines 339/342/345. Section 6's "mirror AD-525/AD-530" instruction is grounded. ✅

## Verified Against Codebase (2026-05-04)

```
grep -n "class PersonalityTraits" src/probos/crew_profile.py
   51: class PersonalityTraits:

grep -rn "spc_calibration_store" src/probos/
   (no matches — Section 4 introduces)

grep -rn "SPC_RULE_VIOLATED" src/probos/
   (no matches — Section 0 introduces)

grep -n "spc:" src/probos/config.py
   (no matches in SystemConfig fields — Section 5 introduces; no collision)

grep -n "_wire_creative_expression\|_wire_classification_gate\|_wire_gap_remediation_tracker" src/probos/startup/finalize.py
   80: def _wire_creative_expression(...)
  105: def _wire_classification_gate(...)
  122: def _wire_gap_remediation_tracker(...)
  339: if _wire_creative_expression(runtime=runtime, config=config):
  342: if _wire_classification_gate(runtime=runtime, config=config):
  345: if _wire_gap_remediation_tracker(runtime=runtime, config=config):

grep -n "class EventType" src/probos/events.py
   20: class EventType(str, Enum):
```

---

**Tolerance check (relaxed convention #15):** 0 Required, 3 Recommended, 3 Nits. Well under the 1-⚠️ ceiling. Approve.

**Disposition:** ✅ Approved. Builder may proceed. Recommended findings should be addressed in a quick revision pass to give the Builder explicit SEARCH/REPLACE anchors for Sections 5 and 6 — these will save Builder cycles on the wiring step. Nits are optional cleanup.
