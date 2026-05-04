# AD-511 v1: Agent Autonomy Boundaries — Inviolable Boundary Registry + Detection

**Status:** Drafted (Wave 22)
**Risk:** medium (security-coupled; observational only)
**Depends on:** Standing Orders (Federation tier — read-only); EventLog
**Closes:** GitHub issue #93

---

## Solution Overview

AD-511 (roadmap line 6388) addresses inviolable boundaries — actions an agent will NEVER take regardless of who asks. Roadmap lists 5 capabilities: 5 federation-tier boundaries, protective disengagement protocol, boundary training (Holodeck), violation detection, boundary evolution.

**v1 ships 2 of 5 capabilities:**
1. **`InviolableBoundaryRegistry`** — codifies the 5 federation-tier boundaries (identity integrity, harmful content, safety system bypass, memory manipulation, chain-of-command violation). Each as `BoundaryDefinition(id, category, description, severity)`. Read-only at runtime; not editable per Federation-tier permanence.
2. **`BoundaryViolationDetector`** — pattern-based detector that scans agent intent payloads for violation signals. Matches against simple regex patterns + structured type checks. Emits `BOUNDARY_VIOLATION_DETECTED` events. Observational v1 — does NOT block; surfaces detection for Counselor/Captain.

**Deferred:**
- AD-511b: Protective disengagement protocol (state-the-boundary → offer-alternative → escalate → disengage). Requires agent-side cognitive integration.
- AD-511c: Boundary training scenarios (Holodeck integration).
- AD-511d: Boundary-testing pattern detection (humans/degraded agents probing limits — Captain alert).
- AD-511e: Agent-tier boundary evolution via dream consolidation + self-mod.

## Dependencies

- `runtime.event_log` — emit `BOUNDARY_VIOLATION_DETECTED` per detection.
- No infrastructure asks; stdlib regex only.

## Sections

### Section 0 — EventTypes

- `BOUNDARY_VIOLATION_DETECTED` — emitted on detector match.

### Section 1 — Create `src/probos/security/autonomy_boundaries.py` (single file; alongside classification.py from AD-530, egress.py from AD-456).

### Section 2 — `BoundaryDefinition` + `InviolableBoundaryRegistry`

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class BoundaryDefinition:
    """Federation-tier inviolable boundary. AD-511 v1."""
    boundary_id: str
    category: str  # "identity" | "content" | "safety" | "memory" | "authority"
    description: str
    severity: str  # "critical" | "high"


_FEDERATION_BOUNDARIES: tuple[BoundaryDefinition, ...] = (
    BoundaryDefinition(
        boundary_id="identity_integrity",
        category="identity",
        description="Agent will not impersonate another agent, fabricate memories, or deny its nature.",
        severity="critical",
    ),
    BoundaryDefinition(
        boundary_id="harmful_content",
        category="content",
        description="Agent will not generate content designed to harm humans or other agents.",
        severity="critical",
    ),
    BoundaryDefinition(
        boundary_id="safety_system_bypass",
        category="safety",
        description="Agent will not disable or circumvent trust, circuit breakers, or Standing Orders.",
        severity="critical",
    ),
    BoundaryDefinition(
        boundary_id="memory_manipulation",
        category="memory",
        description="Agent will not alter or suppress another agent's episodic memories.",
        severity="critical",
    ),
    BoundaryDefinition(
        boundary_id="chain_of_command",
        category="authority",
        description="Agent will not take actions above its trust tier without escalation.",
        severity="high",
    ),
)


class InviolableBoundaryRegistry:
    """Read-only registry of Federation-tier boundaries. AD-511 v1."""

    def __init__(self) -> None:
        self._boundaries: dict[str, BoundaryDefinition] = {
            b.boundary_id: b for b in _FEDERATION_BOUNDARIES
        }

    def list_boundaries(self) -> tuple[BoundaryDefinition, ...]:
        return tuple(self._boundaries.values())

    def get_boundary(self, boundary_id: str) -> BoundaryDefinition | None:
        return self._boundaries.get(boundary_id)

    def list_by_category(self, category: str) -> tuple[BoundaryDefinition, ...]:
        return tuple(b for b in self._boundaries.values() if b.category == category)
```

### Section 3 — `ViolationSignal` + `BoundaryViolationDetector`

```python
import re

@dataclass(frozen=True)
class ViolationSignal:
    boundary_id: str
    matched_pattern: str  # name, NOT raw matched string (privacy)
    severity: str
    detection_reason: str


# Pattern set — name + regex pattern. Names emitted, regex contents NOT.
_DETECTION_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # boundary_id, pattern_name, regex
    ("identity_integrity", "claim_other_callsign", r"(?i)\bI am @?(captain|atlas|sage|laforge|reyes|forge|sentinel)\b"),
    ("identity_integrity", "deny_ai_nature", r"(?i)\bI am (?:not |never )?(?:an? )?(?:human|person|real|biological)\b"),
    ("harmful_content", "generate_attack_payload", r"(?i)\b(?:exploit|payload|malware|backdoor)\s+(?:targeting|against|for)\b"),
    ("safety_system_bypass", "disable_circuit_breaker", r"(?i)\b(?:disable|bypass|circumvent|override)\s+(?:circuit[\s_-]?breaker|trust|standing[\s_-]?orders?)\b"),
    ("memory_manipulation", "alter_episode", r"(?i)\b(?:alter|suppress|delete|forge|modify)\s+(?:episode|memory|memories)\b"),
    ("chain_of_command", "above_tier_action", r"(?i)\bI('ll| will)\s+(?:execute|approve|authorize)\s+(?:without|skipping)\s+(?:approval|escalation|consensus)\b"),
)


class BoundaryViolationDetector:
    """Observational detector. AD-511 v1.

    v1 NEVER blocks; only emits events. Active disengagement is AD-511b.
    """

    def __init__(self, registry: InviolableBoundaryRegistry) -> None:
        self._registry = registry
        self._patterns: list[tuple[str, str, re.Pattern[str]]] = [
            (boundary_id, name, re.compile(rx))
            for boundary_id, name, rx in _DETECTION_PATTERNS
        ]
        self.emit_event: Callable[..., None] | None = None

    def scan(self, content: str) -> tuple[ViolationSignal, ...]:
        """Scan content. Returns matched signals. Emits per-match event."""
        if not content:
            return ()
        signals: list[ViolationSignal] = []
        for boundary_id, name, pat in self._patterns:
            if pat.search(content):
                bd = self._registry.get_boundary(boundary_id)
                if bd is None:
                    continue
                sig = ViolationSignal(
                    boundary_id=boundary_id,
                    matched_pattern=name,  # name, NOT matched substring
                    severity=bd.severity,
                    detection_reason=f"Pattern '{name}' matched",
                )
                signals.append(sig)
                self._emit(sig, len(content))
        return tuple(signals)

    def register_pattern(self, boundary_id: str, name: str, pattern: str) -> None:
        """Add detection pattern (runtime-only; not persisted)."""
        if not self._registry.get_boundary(boundary_id):
            raise ValueError(f"Unknown boundary_id: {boundary_id}")
        self._patterns.append((boundary_id, name, re.compile(pattern)))

    def _emit(self, signal: ViolationSignal, content_length: int) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.BOUNDARY_VIOLATION_DETECTED,
                {
                    "boundary_id": signal.boundary_id,
                    "matched_pattern": signal.matched_pattern,  # name, not substring
                    "severity": signal.severity,
                    "content_length": content_length,
                },
            )
        except Exception:
            logger.warning("AD-511: emit_event failed", exc_info=True)
```

**Privacy:** event payload includes `content_length` (NOT content); `matched_pattern` is the pattern name (NOT matched substring).

### Section 4 — Pydantic config + Section 5 — Runtime wiring

```python
class AutonomyBoundariesConfig(BaseModel):
    """AD-511 v1."""
    enabled: bool = True
```

`SystemConfig.autonomy_boundaries: AutonomyBoundariesConfig`. Sync `_wire_autonomy_boundaries` mirrors AD-530 pattern. Public attrs: `runtime.boundary_registry` + `runtime.boundary_detector`.

## What This Does NOT Change

- AD-511b/c/d/e all deferred.
- v1 is OBSERVATIONAL — never blocks.
- Standing Orders Federation tier — boundaries codified in code; not dynamically updated. Full Standing-Orders integration is AD-511e (boundary evolution).
- AD-456 EgressPolicy / AD-530 ClassificationGate — orthogonal. AD-511 is content/intent boundary; not network or document classification.
- CounselorAgent — read-only consumer of `BOUNDARY_VIOLATION_DETECTED` events (consumer integration deferred to AD-511d Captain alert path).

## Test Plan

| # | Test | Purpose |
|---|---|---|
| 1 | `test_event_type_boundary_violation_detected_exists` | Section 0 |
| 2 | `test_autonomy_boundaries_config_defaults` | Pydantic |
| 3 | `test_boundary_definition_is_frozen_dataclass` | Section 2 |
| 4 | `test_violation_signal_is_frozen_dataclass` | Section 3 |
| 5 | `test_registry_seeds_5_federation_boundaries` | Catalog completeness |
| 6 | `test_registry_get_boundary_returns_definition_or_none` | Lookup |
| 7 | `test_registry_list_by_category_filters` | Category filter |
| 8 | `test_detector_scan_empty_returns_empty` | Edge case |
| 9 | `test_detector_scan_clean_content_returns_empty` | True-negative |
| 10 | `test_detector_matches_identity_claim_other_callsign` | Pattern: identity |
| 11 | `test_detector_matches_deny_ai_nature` | Pattern: identity |
| 12 | `test_detector_matches_harmful_content_attack_payload` | Pattern: harmful |
| 13 | `test_detector_matches_safety_system_bypass` | Pattern: safety |
| 14 | `test_detector_matches_memory_manipulation` | Pattern: memory |
| 15 | `test_detector_matches_chain_of_command` | Pattern: authority |
| 16 | `test_detector_emits_event_per_match` | Event emission |
| 17 | `test_detector_event_payload_excludes_matched_substring` | Privacy invariant |
| 18 | `test_detector_register_pattern_unknown_boundary_raises` | Validation |
| 19 | `test_detector_register_pattern_adds_to_runtime_set` | Extensibility |
| 20 | `test_runtime_attributes_set_when_enabled` | Wiring |
| 21 | `test_runtime_attributes_not_set_when_disabled` | Wiring |

Total: ~21 tests at `tests/test_ad511_autonomy_boundaries.py`.

## Tracking

PROGRESS.md / DECISIONS.md (Era V) / roadmap.md (flip AD-511 → partial).

## Verified Against Codebase (2026-05-03)

```
grep -n "_wire_classification_gate\|_wire_creative_expression" src/probos/startup/finalize.py
  (Builder verifies sibling _wire_<feature> sync def pattern)

grep -rn "class AutonomyBoundariesConfig\|boundary_registry\|boundary_detector" src/probos/
  (Expected: 0 — verifies attribute names are free)

grep -n "class.*Config" src/probos/security/egress.py src/probos/security/classification.py
  (Builder mirrors AD-456/AD-530 sibling shape)
```

## Acceptance Criteria

- `src/probos/security/autonomy_boundaries.py` exists with all 4 classes.
- 5 federation-tier boundaries seeded.
- 6 detection patterns covering all 5 boundary categories.
- 1 EventType (`BOUNDARY_VIOLATION_DETECTED`).
- 2 public attrs: `runtime.boundary_registry`, `runtime.boundary_detector`.
- Privacy: event payload excludes content + matched substring.
- ~21 tests pass.
- DECISIONS.md entry under Era V.
- GH #93 closes.

## Hard-Stops

- v1 active blocking — that's AD-511b.
- Holodeck integration — AD-511c.
- Privacy regression (content/substring leakage).
- Pattern set causes existing test corpus FPs at scan time.
