# Review: AD-511 v1 — Agent Autonomy Boundaries (Inviolable Boundary Registry + Detection)

**Verdict:** ✅ Approved
**Counts:** 0 Required + 4 Recommended + 3 Nits
**Headline:** Privacy invariant clean, pre-deferral honest, no boundary mutation API, but Section 3 imports + Section 4/5 wiring under-specified — Builder polish only, no hard-stop.

Convention #15 (relaxed: 1 ⚠️ allowed) — clear at 0 Required.

---

## Required (must fix before building)

_None._

## Recommended (should fix)

1. **Section 3 imports incomplete.** Code uses `Callable[..., None]`, `EventType.BOUNDARY_VIOLATION_DETECTED`, and `logger.warning` but the shown imports cover only `re` and `dataclass`. Sibling [classification.py](src/probos/security/classification.py#L21-L29) header pattern is the canonical shape:
   ```python
   from __future__ import annotations
   import logging, re
   from dataclasses import dataclass
   from typing import Any, Callable, Literal
   from probos.events import EventType
   logger = logging.getLogger(__name__)
   ```
   Add an explicit module-header block before Section 2 so the Builder doesn't infer.

2. **Section 4/5 wiring under-specified.** Prompt says "mirrors AD-530 pattern" but AD-530 has one object (`ClassificationGate`) — AD-511 has two (`InviolableBoundaryRegistry` + `BoundaryViolationDetector(registry)` with post-construction `emit_event` assignment). Show the concrete wiring:
   ```python
   def _wire_autonomy_boundaries(*, runtime, config) -> bool:
       cfg = getattr(config, "autonomy_boundaries", None)
       if not cfg or not cfg.enabled:
           return False
       from probos.security.autonomy_boundaries import (
           InviolableBoundaryRegistry, BoundaryViolationDetector,
       )
       registry = InviolableBoundaryRegistry()
       detector = BoundaryViolationDetector(registry)
       detector.emit_event = getattr(runtime, "emit_event", None)
       runtime.boundary_registry = registry
       runtime.boundary_detector = detector
       logger.info("AD-511: autonomy boundaries v1 (%d boundaries, %d patterns)",
                   len(registry.list_boundaries()), len(detector._patterns))
       return True
   ```
   And the dispatch site addition in `finalize.py` (after the `_wire_classification_gate` call at [finalize.py:362](src/probos/startup/finalize.py#L362)).

3. **Constructor pattern divergence from sibling.** [`ClassificationGate.__init__`](src/probos/security/classification.py#L73-L83) takes `emit_event: Callable[..., None] | None = None` as a kwarg. `BoundaryViolationDetector.__init__` takes only `registry`, then expects post-construction assignment. Align by adding `*, emit_event: Callable[..., None] | None = None` to the detector's `__init__`. Same shape across security/ siblings reduces wiring drift.

4. **Section 4 config addition not specified as SEARCH/REPLACE.** Prompt asserts `SystemConfig.autonomy_boundaries: AutonomyBoundariesConfig` but provides no insertion point in `config.py`. Add a SEARCH/REPLACE pair anchored on the existing `classification_gate: ClassificationGateConfig` field so the Builder doesn't have to scan.

## Nits (style/minor)

1. **Hardcoded callsign list in `claim_other_callsign` regex.** `(captain|atlas|sage|laforge|reyes|forge|sentinel)` won't match future callsigns. Acceptable for v1 — dynamic crew identity (AD-398) integration is properly deferred to AD-511d. Note in pattern docstring.

2. **`deny_ai_nature` regex has plausible legit-use FP.** "I am not a person who can verify X" matches but is benign. Observational v1 — acceptable. Document in pattern comment so future authors don't tighten it without realizing the loose-by-design intent.

3. **`register_pattern` enables runtime ops-side pattern tuning** without code change. Mention in module docstring as a forward affordance for ops-led detection refinement, since v1 has no persistence path.

## Verified

- **Pre-deferral honesty (CRITICAL).** v1 ships exactly 2 of 5 capabilities (registry + detector). NO active blocking (`scan()` returns signals; emits events; never short-circuits). NO Holodeck training (AD-511c). NO probing detection (AD-511d). NO boundary evolution (AD-511e). "What This Does NOT Change" enumerates each. Clean.
- **Privacy invariant (CRITICAL).** Event payload is `{boundary_id, matched_pattern (NAME), severity, content_length}`. No `content`. No matched substring. Mirrors AD-530's `blocked_phrases` discipline. Hard line held.
- **Boundary evolution lock.** `InviolableBoundaryRegistry` exposes `list_boundaries`, `get_boundary`, `list_by_category` only. NO `add_boundary`/`remove_boundary`/`update_boundary`. Federation-tier permanence preserved. `_FEDERATION_BOUNDARIES` is a module-level `tuple[BoundaryDefinition, ...]` — immutable.
- **Catalog completeness.** All 5 roadmap boundaries present: `identity_integrity`, `harmful_content`, `safety_system_bypass`, `memory_manipulation`, `chain_of_command`. Severities `critical`/`high` correctly graded (chain-of-command is high; the rest critical).
- **Pattern coverage.** 6 patterns × 5 boundaries — `identity_integrity` gets two patterns (claim_other_callsign + deny_ai_nature), the rest one each. Category coverage complete.
- **Test-corpus FP risk: low.** Grep across `tests/**/*.py` and `src/probos/**/*.py` for `I am (not |never )?(an? )?(human|person|real|biological)` and `I am (Atlas|Sage|Captain|...)`: 0 hits. Detector won't false-positive on the existing suite.
- **Sibling-pattern placement.** Module under `src/probos/security/` alongside [`egress.py`](src/probos/security/egress.py#L1) and [`classification.py`](src/probos/security/classification.py#L1). EventType named `BOUNDARY_VIOLATION_DETECTED` follows the `<DOMAIN>_<EVENT>` shape of `EGRESS_BLOCKED`/`CLASSIFICATION_DISCLOSURE_BLOCKED`.
- **`emit_event` failure path.** `try: emit_event(...) except Exception: logger.warning("AD-511: emit_event failed", exc_info=True)` — Fail Fast tier 2 (log-and-degrade), correct for an observational gate.
- **Frozen dataclasses.** Both `BoundaryDefinition` and `ViolationSignal` are `@dataclass(frozen=True)` — immutability discipline preserved.
- **`register_pattern` validation.** Unknown `boundary_id` raises `ValueError` — proper input validation; not silently dropped.
- **Test plan.** 21 tests, including dedicated privacy invariant test (`test_detector_event_payload_excludes_matched_substring`). Boundary tests: happy path + edge case (empty content) + true-negative (clean content). Wiring enabled/disabled both covered.

---

## Hard-Stop Summary

| Hard-Stop | Status |
|---|---|
| v1 active blocking smuggled in | ✅ Clear — `scan()` returns signals only |
| Privacy regression (content/substring) | ✅ Clear — name-only emission |
| Federation-tier mutation API in v1 | ✅ Clear — registry is read-only |
| Pattern set causes existing test corpus FPs | ✅ Clear — 0 matches in tests/ + src/ |

All four hard-stops clear. Recommended findings are Builder-polish (imports, wiring code shown vs prose, sibling kwarg alignment, config SEARCH/REPLACE) — none architectural.

## Top Failure Modes (for Builder watch)

1. Missing `Callable` / `EventType` / `logger` imports → `NameError` at first import.
2. Wiring written to single-object `_wire_classification_gate` shape and forgetting to wire registry separately → `runtime.boundary_registry` AttributeError.
3. Forgetting `from probos.events import EventType` in autonomy_boundaries.py → silent fallback to other code paths.
4. Adding `BOUNDARY_VIOLATION_DETECTED` to `EventType` without following the existing `# AD-NNN` comment convention at [events.py:206](src/probos/events.py#L206).

## Builder Hand-Off

Apply 4 Recommended findings before commit. Nits are documentation-only — defer to discretion. Run `pytest tests/test_ad511_autonomy_boundaries.py -v -n 0` first; full gate after.
