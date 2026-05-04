"""AD-522 v1: Western Electric rule set (4 of 8) for SPC violation detection."""

from __future__ import annotations

from dataclasses import dataclass

from probos.cognitive.spc.calibration_profile import AgentCalibrationProfile


@dataclass(frozen=True)
class RuleViolation:
    rule_name: str
    description: str
    sample_index: int  # index into the checked window


class WesternElectricRules:
    """4 of 8 Western Electric / Nelson rules. AD-522 v1.

    Deferred rules (5–8): trend (6+ rising), 14 alternating, 15 within 1σ
    (stratification), 8 outside 1σ. Ships when AD-522b adds stronger pattern
    detection.
    """

    @staticmethod
    def check(
        profile: AgentCalibrationProfile,
        window_size: int = 20,
    ) -> list[RuleViolation]:
        """Run 4 rules over the most recent ``window_size`` samples."""
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
            window3 = values[i:i + 3]
            above_2sigma = sum(1 for v in window3 if v > mean + 2.0 * stdev)
            below_2sigma = sum(1 for v in window3 if v < mean - 2.0 * stdev)
            if above_2sigma >= 2 or below_2sigma >= 2:
                violations.append(RuleViolation(
                    rule_name="rule_2_two_of_three_zone_a",
                    description=f"2-of-3 points {i}-{i + 2} in Zone A",
                    sample_index=i,
                ))
                break  # one report per scan

        # Rule 3: 4-of-5 consecutive points in Zone B (>1σ same side)
        for i in range(len(values) - 4):
            window5 = values[i:i + 5]
            above_1sigma = sum(1 for v in window5 if v > mean + 1.0 * stdev)
            below_1sigma = sum(1 for v in window5 if v < mean - 1.0 * stdev)
            if above_1sigma >= 4 or below_1sigma >= 4:
                violations.append(RuleViolation(
                    rule_name="rule_3_four_of_five_zone_b",
                    description=f"4-of-5 points {i}-{i + 4} in Zone B",
                    sample_index=i,
                ))
                break

        # Rule 4: 8 consecutive points on same side of centerline
        for i in range(len(values) - 7):
            window8 = values[i:i + 8]
            all_above = all(v > mean for v in window8)
            all_below = all(v < mean for v in window8)
            if all_above or all_below:
                side = "above" if all_above else "below"
                violations.append(RuleViolation(
                    rule_name="rule_4_eight_consecutive_same_side",
                    description=f"8 consecutive points {i}-{i + 7} {side} centerline",
                    sample_index=i,
                ))
                break

        return violations
