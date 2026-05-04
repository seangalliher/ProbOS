# AD-522 v1: Statistical Process Control — Calibration Profile + Western Electric Rules

**Status:** Drafted (Wave 21)
**Risk:** medium (statistical foundation; observational only)
**Depends on:** crew_profile.py (Big Five — shipped); EmergentDetector (consumed read-only); AD-503/504/506 NOT required for v1
**Closes:** GitHub issue #97

---

## Solution Overview

AD-522 in roadmap.md (line 6423) lists 5 SPC capabilities. v1 ships the foundation:

**v1 ships 2 of 5 capabilities** (per convention #14):
1. **`AgentCalibrationProfile`** — per-agent control chart with X̄ (mean), UCL/LCL (Upper/Lower Control Limits), σ (std dev), sample count. Updates via `record_observation(value)`. Computes from a bounded sample window (default 100 most recent observations).
2. **Western Electric / Nelson rule set (4 of 8 rules)** — `WesternElectricRules.check(profile, recent_values)` returns list of `RuleViolation` (rule_name, description, sample_index). Ships rules: (a) 1 point beyond 3σ, (b) 2-of-3 in Zone A (>2σ), (c) 4-of-5 in Zone B (>1σ), (d) 8 consecutive on same side of centerline.

**Deferred:**
- AD-522b: Cp/Cpk process capability indices.
- AD-522c: Graduated response integration (SPC zones → AD-506 Green/Amber/Red).
- AD-522d: Moving-range / continuous recalibration with assignable-vs-common cause distinction.
- AD-522e: Calibration sampling integration with Holodeck onboarding (depends on AD-486).

## Dependencies

- `crew_profile.py:51` (PersonalityTraits Big Five) — read-only consumer (used to inform default control-limit width by neuroticism).
- `runtime.event_log` — emit `SPC_RULE_VIOLATED` per detected violation.
- No infrastructure asks; all stdlib statistics.

## Sections

### Section 0 — EventTypes

- `SPC_RULE_VIOLATED` — emitted when WesternElectricRules.check finds violation(s).

### Section 1 — Create `src/probos/cognitive/spc/` package

- `src/probos/cognitive/spc/__init__.py`
- `src/probos/cognitive/spc/calibration_profile.py`
- `src/probos/cognitive/spc/rules.py`

### Section 2 — `AgentCalibrationProfile`

```python
import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque

@dataclass
class AgentCalibrationProfile:
    """Per-agent SPC control chart. AD-522 v1."""
    agent_id: str
    sample_window: int = 100  # bounded ring
    sigma_multiplier: float = 3.0
    _samples: Deque[float] = field(default_factory=deque)

    def __post_init__(self) -> None:
        if not isinstance(self._samples, deque):
            self._samples = deque(maxlen=self.sample_window)
        elif self._samples.maxlen != self.sample_window:
            self._samples = deque(self._samples, maxlen=self.sample_window)

    def record_observation(self, value: float) -> None:
        self._samples.append(float(value))

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    @property
    def mean(self) -> float:
        return statistics.fmean(self._samples) if self._samples else 0.0

    @property
    def stdev(self) -> float:
        return statistics.stdev(self._samples) if len(self._samples) >= 2 else 0.0

    @property
    def ucl(self) -> float:
        return self.mean + (self.sigma_multiplier * self.stdev)

    @property
    def lcl(self) -> float:
        return self.mean - (self.sigma_multiplier * self.stdev)

    def zone(self, value: float) -> str:
        """Return SPC zone label. Returns 'unknown' when insufficient samples."""
        if self.sample_count < 2 or self.stdev == 0.0:
            return "unknown"
        delta = abs(value - self.mean)
        if delta > 3.0 * self.stdev:
            return "beyond_3sigma"
        if delta > 2.0 * self.stdev:
            return "zone_a"  # 2-3σ
        if delta > 1.0 * self.stdev:
            return "zone_b"  # 1-2σ
        return "zone_c"      # within 1σ

    def recent_values(self, n: int) -> tuple[float, ...]:
        """Most recent n samples (oldest-first)."""
        if n <= 0 or not self._samples:
            return ()
        slice_n = list(self._samples)[-n:]
        return tuple(slice_n)
```

### Section 3 — `WesternElectricRules`

```python
@dataclass(frozen=True)
class RuleViolation:
    rule_name: str
    description: str
    sample_index: int  # index into the checked window


class WesternElectricRules:
    """4 of 8 Western Electric / Nelson rules. AD-522 v1.

    Deferred rules (5-8): trend (6+ rising), 14 alternating, 15 within 1σ
    (stratification), 8 outside 1σ. Ships when AD-522b adds stronger pattern
    detection.
    """

    @staticmethod
    def check(
        profile: AgentCalibrationProfile,
        window_size: int = 20,
    ) -> list[RuleViolation]:
        """Run 4 rules over the most recent window_size samples."""
        if profile.sample_count < 8 or profile.stdev == 0.0:
            return []
        values = profile.recent_values(window_size)
        if not values:
            return []
        mean = profile.mean
        stdev = profile.stdev
        violations: list[RuleViolation] = []

        # Rule 1: 1 point beyond 3σ
        for i, v in enumerate(values):
            if abs(v - mean) > 3.0 * stdev:
                violations.append(RuleViolation(
                    rule_name="rule_1_beyond_3sigma",
                    description=f"Sample {i} ({v:.3f}) beyond 3σ from mean {mean:.3f}",
                    sample_index=i,
                ))

        # Rule 2: 2-of-3 consecutive points in Zone A (>2σ same side)
        for i in range(len(values) - 2):
            window3 = values[i:i+3]
            above_2sigma = sum(1 for v in window3 if v > mean + 2.0 * stdev)
            below_2sigma = sum(1 for v in window3 if v < mean - 2.0 * stdev)
            if above_2sigma >= 2 or below_2sigma >= 2:
                violations.append(RuleViolation(
                    rule_name="rule_2_two_of_three_zone_a",
                    description=f"2-of-3 points {i}-{i+2} in Zone A",
                    sample_index=i,
                ))
                break  # one report per scan

        # Rule 3: 4-of-5 consecutive points in Zone B (>1σ same side)
        for i in range(len(values) - 4):
            window5 = values[i:i+5]
            above_1sigma = sum(1 for v in window5 if v > mean + 1.0 * stdev)
            below_1sigma = sum(1 for v in window5 if v < mean - 1.0 * stdev)
            if above_1sigma >= 4 or below_1sigma >= 4:
                violations.append(RuleViolation(
                    rule_name="rule_3_four_of_five_zone_b",
                    description=f"4-of-5 points {i}-{i+4} in Zone B",
                    sample_index=i,
                ))
                break

        # Rule 4: 8 consecutive points on same side of centerline
        for i in range(len(values) - 7):
            window8 = values[i:i+8]
            all_above = all(v > mean for v in window8)
            all_below = all(v < mean for v in window8)
            if all_above or all_below:
                side = "above" if all_above else "below"
                violations.append(RuleViolation(
                    rule_name="rule_4_eight_consecutive_same_side",
                    description=f"8 consecutive points {i}-{i+7} {side} centerline",
                    sample_index=i,
                ))
                break

        return violations
```

### Section 4 — `SPCCalibrationStore` (registry)

```python
class SPCCalibrationStore:
    """Per-agent SPC profiles. AD-522 v1.

    Stores AgentCalibrationProfile instances; runs WesternElectricRules.check
    on demand. Emits SPC_RULE_VIOLATED on every detected violation.
    """

    def __init__(self, runtime: Any, *, sample_window: int = 100) -> None:
        self._runtime = runtime
        self._sample_window = sample_window
        self._profiles: dict[str, AgentCalibrationProfile] = {}
        self.emit_event: Callable[..., None] | None = None

    def get_or_create(self, agent_id: str) -> AgentCalibrationProfile:
        prof = self._profiles.get(agent_id)
        if prof is None:
            prof = AgentCalibrationProfile(
                agent_id=agent_id,
                sample_window=self._sample_window,
            )
            self._profiles[agent_id] = prof
        return prof

    def record_observation(self, agent_id: str, value: float) -> None:
        prof = self.get_or_create(agent_id)
        prof.record_observation(value)

    def check_rules(self, agent_id: str, window_size: int = 20) -> list[RuleViolation]:
        prof = self._profiles.get(agent_id)
        if prof is None:
            return []
        violations = WesternElectricRules.check(prof, window_size=window_size)
        for v in violations:
            self._emit_violation(agent_id, v)
        return violations

    def all_profiles(self) -> tuple[AgentCalibrationProfile, ...]:
        return tuple(self._profiles.values())

    def _emit_violation(self, agent_id: str, violation: RuleViolation) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.SPC_RULE_VIOLATED,
                {
                    "agent_id": agent_id,
                    "rule_name": violation.rule_name,
                    "description": violation.description,
                },
            )
        except Exception:
            logger.warning("AD-522: emit_event failed", exc_info=True)
```

### Section 5 — Pydantic config

```python
class SPCConfig(BaseModel):
    """AD-522 v1."""
    enabled: bool = True
    sample_window: int = 100
```

Wire into `SystemConfig.spc: SPCConfig = Field(default_factory=SPCConfig)`.

### Section 6 — Runtime wiring (finalize.py)

Sync `_wire_spc_calibration` mirroring AD-525/AD-530 pattern. Public attribute `runtime.spc_calibration_store`.

## What This Does NOT Change

- AD-522b/c/d/e — all deferred.
- EmergentDetector — read-only (no integration in v1; AD-522c integrates SPC zones into Graduated Response).
- AD-503 Counselor / AD-504 Self-Monitoring — not consumed by v1.
- AD-486 Holodeck — calibration sampling integration deferred to AD-522e.
- crew_profile.PersonalityTraits — read-only; v1 doesn't yet adjust sigma_multiplier by neuroticism (deferred to AD-522d).

## Test Plan

| # | Test | Purpose |
|---|---|---|
| 1 | `test_event_type_spc_rule_violated_exists` | Section 0 |
| 2 | `test_spc_config_defaults` | Pydantic |
| 3 | `test_calibration_profile_initial_state` | Empty profile: mean=0, stdev=0, sample_count=0 |
| 4 | `test_calibration_profile_record_observation_appends` | Ring buffer |
| 5 | `test_calibration_profile_bounded_window_evicts_oldest` | maxlen behavior |
| 6 | `test_calibration_profile_mean_stdev_ucl_lcl` | Statistics computation |
| 7 | `test_calibration_profile_zone_returns_unknown_below_two_samples` | Defensive |
| 8 | `test_calibration_profile_zone_classification_correct` | Zone boundaries (within 1σ, 1-2σ, 2-3σ, beyond) |
| 9 | `test_calibration_profile_recent_values_returns_n` | Window slicing |
| 10 | `test_western_electric_rules_no_violations_when_insufficient_samples` | Defensive |
| 11 | `test_western_electric_rules_no_violations_when_zero_stdev` | Defensive |
| 12 | `test_western_electric_rules_rule_1_beyond_3sigma` | Single outlier |
| 13 | `test_western_electric_rules_rule_2_two_of_three_zone_a` | Pattern detection |
| 14 | `test_western_electric_rules_rule_3_four_of_five_zone_b` | Pattern detection |
| 15 | `test_western_electric_rules_rule_4_eight_consecutive_same_side` | Sustained shift |
| 16 | `test_western_electric_rules_in_control_signal_yields_no_violations` | True-negative |
| 17 | `test_spc_calibration_store_get_or_create_idempotent` | Registry behavior |
| 18 | `test_spc_calibration_store_check_rules_emits_event_per_violation` | Event emission |
| 19 | `test_spc_calibration_store_all_profiles_returns_tuple` | Iterator behavior |
| 20 | `test_runtime_attribute_set_when_enabled` | Public-attribute wiring |
| 21 | `test_runtime_attribute_not_set_when_disabled` | Disabled config skips wiring |

Total: ~21 tests at `tests/test_ad522_spc.py`.

## Tracking

1. **PROGRESS.md:** prepend AD-522 v1 entry.
2. **DECISIONS.md:** Era V entry (problem/decision/why/deferred).
3. **roadmap.md:** flip AD-522 status to `partial — v1 ships AgentCalibrationProfile + WesternElectricRules (4 of 8); Cp/Cpk + graduated-response integration + moving-range + Holodeck calibration deferred to AD-522b/c/d/e`.

## Verified Against Codebase (2026-05-03)

```
grep -n "class PersonalityTraits" src/probos/crew_profile.py
   51: class PersonalityTraits (read-only consumer)

grep -n "_wire_creative_expression\|_wire_classification_gate\|_wire_gap_remediation_tracker" src/probos/startup/finalize.py
  (Builder verifies sync _wire_<feature> pattern)

grep -rn "class SPCConfig\|spc_calibration_store" src/probos/
  (Expected: 0 — verifies attribute name is free)
```

## Acceptance Criteria

- `src/probos/cognitive/spc/` package exists.
- `AgentCalibrationProfile` + `RuleViolation` + `WesternElectricRules` + `SPCCalibrationStore` ship.
- 1 new EventType (`SPC_RULE_VIOLATED`).
- `SPCConfig` Pydantic class wired into SystemConfig.
- Public attribute `runtime.spc_calibration_store` (no underscore).
- ~21 tests pass.
- DECISIONS.md entry under Era V.
- GH issue #97 closes.

## Hard-Stops

- v1 scope creep — AD-522b/c/d/e functionality smuggled in.
- EmergentDetector integration in v1 — that's AD-522c.
- Holodeck calibration in v1 — that's AD-522e.
- Pre-check finds new phantoms.
