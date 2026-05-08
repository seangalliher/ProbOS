"""AD-700: Multi-Level Diagnostics (L1-L5) for the Medical team.

LCARS-formalized diagnostic depth levels. The Captain (or any caller) can
specify how deep a diagnosis should run. Levels map to (scope, depth, LLM
tier, expected duration):

| Level | Scope            | Depth                            | LLM Usage   |
|-------|------------------|----------------------------------|-------------|
| L5    | Single metric    | Current value only               | None        |
| L4    | Specific subsys  | Current + recent trend           | None        |
| L3    | Target system    | Historical + anomaly detection   | Fast tier   |
| L2    | Full department  | Comprehensive automated sweep    | Fast tier   |
| L1    | Ship-wide        | Multi-turn root cause + cross-XD | Deep tier   |

Lower number = deeper analysis. L5 is instant heartbeat-style; L1 is the
full ship-wide root-cause analysis.

Numeric ordering is intentionally inverted from the enum value (per the
roadmap spec). Use ``DiagnosticLevel.depth_rank`` (1-5, larger = deeper)
when you need to compare "is X deeper than Y".
"""

from __future__ import annotations

from enum import Enum


class DiagnosticLevel(str, Enum):
    """LCARS-style diagnostic depth tiers (L5 = shallow, L1 = deepest)."""

    L5 = "L5"  # Single metric, current value only.
    L4 = "L4"  # Subsystem, current + recent trend.
    L3 = "L3"  # Target system, historical + anomaly detection.
    L2 = "L2"  # Full department, comprehensive sweep.
    L1 = "L1"  # Ship-wide, multi-turn root cause + cross-department correlation.

    @property
    def depth_rank(self) -> int:
        """Return 1..5 where larger = deeper. L5 -> 1, L1 -> 5."""
        return {self.L5: 1, self.L4: 2, self.L3: 3, self.L2: 4, self.L1: 5}[self]

    @property
    def llm_tier(self) -> str | None:
        """Recommended LLM tier for this depth. ``None`` means no LLM.

        Maps per AD-700 / roadmap spec: L4-L5 are deterministic, L2-L3 use
        the fast tier, L1 uses the deep tier.
        """
        return {
            self.L5: None,
            self.L4: None,
            self.L3: "fast",
            self.L2: "fast",
            self.L1: "deep",
        }[self]

    @property
    def expected_duration_label(self) -> str:
        """Human-readable expected duration band for HXI / status display."""
        return {
            self.L5: "instant",
            self.L4: "seconds",
            self.L3: "10-30s",
            self.L2: "1-2min",
            self.L1: "minutes",
        }[self]


def parse_level(value: str | int | DiagnosticLevel | None, *, default: DiagnosticLevel = DiagnosticLevel.L3) -> DiagnosticLevel:
    """Parse a level token into a ``DiagnosticLevel``.

    Accepts:
      - ``DiagnosticLevel`` instances (passthrough).
      - ``"L5"`` / ``"l3"`` / ``"L1"`` / ... case-insensitive.
      - ``"5"`` / ``5`` / ... numeric forms (1..5).
      - ``None`` -> ``default``.

    Returns ``default`` for any unparseable input -- never raises. Diagnostics
    must degrade gracefully; an unknown level is logged elsewhere as a
    warning and falls back to the default depth.
    """
    if value is None:
        return default
    if isinstance(value, DiagnosticLevel):
        return value
    s = str(value).strip().upper()
    if not s:
        return default
    if s in ("1", "2", "3", "4", "5"):
        s = "L" + s
    try:
        return DiagnosticLevel(s)
    except ValueError:
        return default
