# AD-665: Corroboration Source Validation

**Status:** Ready (production no-op until AD-663 lands; tests validate logic with synthetic episodes)
**Issue:** #343
**Scope:** OSS (`src/probos/cognitive/social_verification.py`, `src/probos/config.py`, `tests/test_social_verification.py`)

## Context

AD-662 added provenance metadata fields to `AnchorFrame` (`source_origin_id`, `artifact_version`, `anomaly_window_id`) and a binary `_share_artifact_ancestry()` check. Current limitation: the check is exact-match only (`source_origin_id` equality). Reed (Science) submitted 4 improvement proposals identifying gaps:

1. **Transitive ancestry** — A→B→C chain: if Source A produced Artifact B which produced Artifact C, observations anchored to B and C share ancestry but have different `source_origin_id` values. Current binary check misses this. **Deferred to a future AD** — requires extending `AnchorFrame` with `parent_origin_ids` or an external lineage map, neither of which exists today.
2. **Version-aware comparison** — Same `source_origin_id` but different `artifact_version` may represent genuinely independent observations if the artifact changed materially between versions. **Addressed in this AD** via graded independence weight.
3. **Provenance validation reporting** — No structured output about *why* corroboration was discounted. Agents (and diagnostics) can't inspect the reasoning. **Addressed in this AD** via `ProvenanceValidationResult` report.
4. **Configurable similarity threshold** — Hard-coded binary match doesn't support tunable strictness. **Addressed in this AD** via `version_independence_weight` config.

## Implementation

### 1. Add `ProvenanceValidationResult` dataclass to `src/probos/cognitive/social_verification.py`

Add after the existing `CascadeRiskResult` dataclass (around line 54):

```python
@dataclass(frozen=True)
class ProvenanceValidationResult:
    """AD-665: Structured report of provenance-based independence validation."""
    total_pairs_checked: int
    independent_pairs: int
    shared_ancestry_pairs: int  # Same origin + same version
    discounted_pairs: int  # Same origin, different version
    ancestry_details: list[dict[str, Any]]  # Per-pair breakdown (ids + reason + weight only)
```

**Privacy invariant:** `ancestry_details` entries MUST NOT contain claim text, anchor participants, or any content-bearing field. Each entry contains only: `{"episode_a": str, "episode_b": str, "reason": str, "weight": float}`. Episode IDs must be opaque identifiers, not content-bearing. This matches the module's existing privacy principle (line 6, line 35): agents learn whether and who, never what.

### 2. Add config fields to `SocialVerificationConfig` in `src/probos/config.py`

Add to the existing `SocialVerificationConfig` class (around line 646), after the `anomaly_window_discount` field:

```python
    # Provenance validation (AD-665)
    provenance_version_independence_weight: float = 0.7  # Weight for same-origin-different-version pairs (0.0=reject, 1.0=full independence)
    provenance_validation_enabled: bool = True  # Master toggle for AD-665 graded validation
```

**Naming rationale:** `version_independence_weight` (not `version_discount`) — value represents independence weight *retained* (1.0 = fully independent, 0.0 = no independence), consistent with how the weight is used in the scoring formula.

**Default rationale:** 0.7 has no empirical basis. Initial value chosen as "mostly independent" — same-source-different-version pairs should still contribute meaningfully but less than fully independent pairs. Tunable per deployment.

### 3. Extend `compute_anchor_independence()` with graded provenance weights

Modify the existing `compute_anchor_independence()` function (line 135) to replace the binary shared-ancestry veto with graded weights. This is a **replacement, not an addition** — there is one independence score, not two.

**Current code (lines 168-173):**
```python
            # AD-662: Shared ancestry is an absolute veto — overrides both
            # spatiotemporal independence AND time separation
            if _share_artifact_ancestry(a, b):
                pass  # Not independent, regardless of other signals
            elif _are_independently_anchored(a, b) or _time_separated(episodes[i], episodes[j]):
                independent_weight += pair_weight
```

**Replace with:**
```python
            # AD-665: Graded provenance independence (replaces AD-662 binary veto)
            if _share_artifact_ancestry(a, b):
                # Same source_origin_id — check if version differs
                version_a = getattr(a, "artifact_version", "") or ""
                version_b = getattr(b, "artifact_version", "") or ""
                if version_a and version_b and version_a != version_b:
                    # Same origin, different version — partial independence
                    independent_weight += pair_weight * version_independence_weight
                # else: Same origin + same version (or missing version) → 0 weight (full veto)
            elif _are_independently_anchored(a, b) or _time_separated(episodes[i], episodes[j]):
                independent_weight += pair_weight
```

**Update function signature** to accept the new parameter:

```python
def compute_anchor_independence(
    episodes: list[Any],
    anomaly_discount: float = 0.5,
    version_independence_weight: float = 0.0,  # AD-665: 0.0 = AD-662 binary veto behavior; callers opt in via config
) -> float:
```

**Anomaly discount handling:** The anomaly discount is applied exactly once per pair, on the `pair_weight` (denominator side), same as before. No double-counting — the version independence weight applies to the numerator (how much independence credit a pair gets), while the anomaly discount applies to the denominator (how much the pair counts toward total weight). These are orthogonal.

### 4. Build provenance report alongside scoring

Add a new module-level function `build_provenance_report()` that mirrors the pair iteration in `compute_anchor_independence()` but collects structured diagnostics instead of computing a score:

```python
def build_provenance_report(
    episodes: list[Any],
    *,
    version_independence_weight: float = 0.0,  # AD-665: 0.0 = AD-662 binary veto; callers pass config
) -> ProvenanceValidationResult:
```

Logic:
- Iterate all unique pairs of episodes (same pattern as `compute_anchor_independence()`)
- For each pair, classify as: independent / shared_ancestry (same origin + same version) / discounted (same origin + different version)
- Increment `independent_pairs` for each pair that is neither shared-ancestry nor version-discounted
- Build `ancestry_details` list with one dict per non-independent pair: `{"episode_a": id_a, "episode_b": id_b, "reason": "shared_ancestry" | "version_discounted", "weight": float}`
- **Privacy assertion:** Only episode IDs appear in the details. No content, no participants, no anchor metadata beyond the classification reason and weight. Episode IDs are obtained via `getattr(episode, "id", "")` — if any episode type uses content-derived IDs, hash them before inclusion (use `hashlib.sha256(id.encode()).hexdigest()[:16]`). Current `EpisodicMemory` uses UUID-based IDs, so this is defensive.
- **Privacy guard in code:** Add a runtime assertion to enforce the allowed keys:

```python
_ALLOWED_DETAIL_KEYS = frozenset({"episode_a", "episode_b", "reason", "weight"})
# When constructing each detail dict:
detail = {"episode_a": id_a, "episode_b": id_b, "reason": ..., "weight": ...}
assert set(detail.keys()) <= _ALLOWED_DETAIL_KEYS  # AD-665 privacy invariant
```
- Return `ProvenanceValidationResult` with counts and details

**Performance note:** This is an additional O(N²) pass over the episode pairs. At current k values (≤10), this is negligible. Add the following TODO comment in code:

```python
# AD-665 TODO: At k > ~50, fold this into compute_anchor_independence()
# to avoid two O(N²) passes. Track separately.
```

### 5. Wire graded independence + report into `check_corroboration()`

In `SocialVerificationService.check_corroboration()` (line 198), at the existing `compute_anchor_independence()` call (line 234):

1. Pass `version_independence_weight=self._config.provenance_version_independence_weight if self._config.provenance_validation_enabled else 0.0` to `compute_anchor_independence()`. When disabled, 0.0 produces identical results to AD-662's binary veto (function default is also 0.0, so omitting works too — but explicit is clearer).
2. If enabled, also call `build_provenance_report(episodes, version_independence_weight=self._config.provenance_version_independence_weight)` and attach the result to the anchor summary. If disabled, set `anchor_summary["provenance_validation"]` to `None` (key must always be present — consumers can rely on it existing in both modes).

**There is one score, one truth.** No `min()` of two scores. The graded weight is integrated directly into `compute_anchor_independence()`.

### 6. Wire into `check_cascade_risk()`

In `check_cascade_risk()` (line 355), at the existing `compute_anchor_independence()` call (line 421):

1. Same pattern as Section 5: pass `version_independence_weight=self._config.provenance_version_independence_weight if self._config.provenance_validation_enabled else 0.0`.
2. No provenance report needed here — cascade risk is a quick check, not a diagnostic. Add a field comment in `CascadeRiskResult`: `# AD-665: provenance_validation report is not attached here — query CorroborationResult.anchor_summary for diagnostic detail.`

### 7. Add provenance report to `CorroborationResult.anchor_summary`

Extend the `anchor_summary` dict construction (around line 311) to include:
- `"provenance_validation"`: The `ProvenanceValidationResult` as a dict (use `dataclasses.asdict()`) when provenance validation was run, else `None`

### 8. Emit `CORROBORATION_PROVENANCE_VALIDATED` event

Add a new `EventType` member in `src/probos/events.py`:

```python
CORROBORATION_PROVENANCE_VALIDATED = "corroboration_provenance_validated"
```

Add a typed event dataclass after `CorroborationVerifiedEvent` (line 734), following the same pattern:

```python
@dataclass
class CorroborationProvenanceValidatedEvent(BaseEvent):
    """AD-665: Emitted when provenance validation detects shared ancestry."""
    event_type: EventType = field(default=EventType.CORROBORATION_PROVENANCE_VALIDATED, init=False)
    requesting_agent: str = ""
    shared_ancestry_pairs: int = 0
    discounted_pairs: int = 0
    total_pairs_checked: int = 0
```

Emit after provenance report is built in `check_corroboration()` when any shared ancestry was detected (`shared_ancestry_pairs > 0 or discounted_pairs > 0`):

```python
if self._emit_event and provenance_result.shared_ancestry_pairs + provenance_result.discounted_pairs > 0:
    self._emit_event(EventType.CORROBORATION_PROVENANCE_VALIDATED.value, {
        "requesting_agent": requesting_agent_id,
        "shared_ancestry_pairs": provenance_result.shared_ancestry_pairs,
        "discounted_pairs": provenance_result.discounted_pairs,
        "total_pairs_checked": provenance_result.total_pairs_checked,
    })
```

**No cooldown guard.** The existing `CORROBORATION_VERIFIED` emit (line 336) has no cooldown either — only `CASCADE_CONFABULATION_DETECTED` uses `cascade_cooldown_seconds`. This event follows the same unguarded pattern. If dedup becomes necessary, add it as a future BF.

### 9. Update `independent_count` loop (line 262) to use graded weights

The `independent_count` loop (line 262-276) also calls `_share_artifact_ancestry()` as a binary veto. Update it to match the new graded logic from Section 3 — if `provenance_validation_enabled`, a same-origin-different-version pair should count toward independence **only if the version_independence_weight >= 0.5** (i.e., the pair contributes at least half of full independence weight). This gives `independent_count` a clear boolean cutoff: the episode "has an independent partner" when the graded weight clears the 0.5 threshold. Add an inline comment: `# AD-665: 0.5 threshold = "majority independent" intuition; tunable via future config if needed`.

**Note:** `independent_anchor_count` in `CorroborationResult` is currently unused by any consumer (confirmed: only set at line 324, never read). The semantic change is safe, but the threshold is now explicit for future consumers. Add a field comment on `CorroborationResult.independent_anchor_count`: `# AD-665: counts episodes with graded weight >= 0.5 (majority-independent threshold)`.

**Note:** This loop (line 262-276) is itself a redundant per-pair scan that mirrors `compute_anchor_independence()` logic. AD-665 does not refactor this redundancy; track separately as tech debt. Adding graded weights here keeps it consistent with Section 3 but does not fix the underlying duplication.

### 10. Fix `_share_artifact_ancestry()` docstring

The docstring (lines 99-108) claims "Same source_origin_id AND same artifact_version is a stronger signal" — but the implementation (lines 113-119) ignores `artifact_version` entirely, checking only `source_origin_id`. Now that AD-665 handles version differentiation in `compute_anchor_independence()`, the docstring must be corrected to match reality.

**Replace the docstring with:**
```python
def _share_artifact_ancestry(anchors_a: Any, anchors_b: Any) -> bool:
    """Check if two anchor frames share source artifact ancestry (AD-662).

    Two observations sharing the same source_origin_id are NOT independent —
    they derive from the same root data, regardless of spatiotemporal separation.
    This function checks source_origin_id only (binary match). Version-aware
    graded scoring is handled by compute_anchor_independence() (AD-665).

    AD-662 preserves existing behavior for None/missing anchors — episodes
    without anchors are not given the ancestry guard. A future AD may tighten this.
    """
```

### 11. Tests — `tests/test_social_verification.py`

Add a new test class `TestProvenanceValidation` after the existing `TestSourceProvenance` class (around line 740). Tests:

1. **`test_provenance_all_independent`** — Episodes with different `source_origin_id` → score 1.0 for provenance contribution, 0 shared pairs in report
2. **`test_provenance_shared_ancestry_same_version`** — Same origin + same version → 0 independence weight for that pair, shared pair counted in report
3. **`test_provenance_shared_ancestry_different_version`** — Same origin + different version → weighted at `version_independence_weight`, discounted pair counted in report
4. **`test_provenance_mixed_pairs`** — 3 episodes: A-B independent, B-C shared ancestry (same version), A-C discounted (same origin, different version, `version_independence_weight=0.7`). Expected: `pair_weight = 1.0` for all 3 (no anomaly), `independent_weight = 1.0 (A-B) + 0.0 (B-C) + 0.7 (A-C) = 1.7`, `total_weight = 3.0`, `score ≈ 0.567`. Assert `pytest.approx(0.567, abs=1e-3)`.
5. **`test_provenance_empty_origin_treated_as_independent`** — Empty `source_origin_id` on either side → independent (defensive)

**Builder pre-flight:** Before writing Test 5, read `social_verification.py:98-119` (`_share_artifact_ancestry`) and verify that empty `source_origin_id` (empty string on either/both sides) returns `False`. If it returns `True` when both are empty strings, that's an AD-662 bug — file a BF, implement the fix in this AD, and add a test for it.
6. **`test_provenance_anomaly_window_orthogonal_to_version_weight`** — Two episodes, same origin, different version, both in anomaly window. Expected math: `pair_weight = 0.5` (anomaly discount), `independent_weight = 0.5 × 0.7 = 0.35`, `score = 0.35 / 0.5 = 0.7`. Assert `0.69 < score < 0.71`. Proves anomaly (denominator) and version weight (numerator) are orthogonal — no double-counting.
7. **`test_provenance_disabled_config`** — `provenance_validation_enabled=False` → binary veto preserved (AD-662 behavior), no provenance report in anchor_summary
8. **`test_provenance_wired_into_corroboration`** — Integration: shared ancestry episodes → assert `corroboration_score` reflects version-weighted independence (score assertion only, not report structure)
9. **`test_provenance_wired_into_cascade`** — Integration: shared ancestry in cascade check → appropriate independence score
10. **`test_provenance_event_emitted_on_shared_ancestry`** — Verify `CORROBORATION_PROVENANCE_VALIDATED` event emitted with correct payload
11. **`test_provenance_no_event_when_all_independent`** — No event emitted when all pairs are independent
12. **`test_provenance_result_in_anchor_summary`** — Assert `anchor_summary["provenance_validation"]` is a dict with the expected keys (`total_pairs_checked`, `independent_pairs`, `shared_ancestry_pairs`, `discounted_pairs`, `ancestry_details`) when enabled. When disabled, assert the key is present with value `None`. Both modes must have the key — consumers can rely on it always existing. Does NOT assert score values — that's test 8's job.
13. **`test_provenance_single_episode_returns_trivial`** — 0 or 1 episode → score 1.0 (via existing compute_anchor_independence behavior), empty report
14. **`test_provenance_details_respect_privacy_boundary`** — Verify `ancestry_details` entries contain ONLY `episode_a`, `episode_b`, `reason`, `weight` keys. No content, no participants, no anchor metadata.
15. **`test_provenance_disabled_reverts_to_ad662`** — Parameterized across two sub-cases: (a) same origin + same version, (b) same origin + different version. In both cases, `provenance_validation_enabled=False` (i.e., `version_independence_weight=0.0`) → 0 independence weight for that pair, identical to AD-662's binary veto. Proves disabling AD-665 reverts to AD-662 semantics for both version scenarios.
16. **`test_provenance_score_interaction`** — An episode set where the version-discounted pair would produce a different score than the binary veto. Assert the graded score is strictly between 0.0 and the fully-independent score — proves the graded logic is actually active.

Use the existing `_make_episode()` and `_rich_anchors()` helpers. Create episodes with provenance fields via `_rich_anchors()` extended or by constructing `AnchorFrame` directly with provenance fields.

## Files Changed

| File | Change |
|------|--------|
| `src/probos/cognitive/social_verification.py` | `ProvenanceValidationResult` dataclass, graded weights in `compute_anchor_independence()`, `build_provenance_report()`, `_share_artifact_ancestry()` docstring fix, wiring in `check_corroboration()` and `check_cascade_risk()`, `independent_count` loop update |
| `src/probos/config.py` | 2 new fields in `SocialVerificationConfig` |
| `src/probos/events.py` | `CORROBORATION_PROVENANCE_VALIDATED` event type + `CorroborationProvenanceValidatedEvent` typed dataclass |
| `tests/test_social_verification.py` | 16 new tests in `TestProvenanceValidation` |

## Tracker Updates

- `PROGRESS.md` — Add AD-665 line: `AD-665 COMPLETE. Corroboration Source Validation — graded provenance independence weights in compute_anchor_independence(), replacing AD-662 binary veto with version-aware scoring. Same-origin-different-version pairs get configurable independence weight (default 0.7). ProvenanceValidationResult report for diagnostics. Privacy-preserving ancestry_details (ids + reason only). Transitive ancestry deferred to future AD. 16 new tests. Issue #343.`
- `docs/development/roadmap.md` — Update AD-665 status from Planned to Complete
- `DECISIONS.md` — Add entry:

### AD-665 — Corroboration Source Validation

**Date:** 2026-04-26
**Status:** Complete
**Depends on:** AD-662 (provenance infrastructure — COMPLETE), AD-663 (producer wiring — FUTURE, AD-665 builds consumer-side assuming fields will be populated)

**Decision:** Replace binary shared-ancestry veto in `compute_anchor_independence()` with graded provenance weights. Same-origin-different-version pairs receive configurable `version_independence_weight` (default 0.7, no empirical basis — tunable per deployment). Single score, no dual-score `min()` combination — graded weight integrates directly into the existing independence formula. Anomaly discount (pair_weight denominator) and version independence weight (numerator credit) are orthogonal, no double-counting. `ProvenanceValidationResult` provides structured diagnostic report without exposing content (privacy invariant preserved). Transitive ancestry (A→B→C chains) explicitly deferred — requires `AnchorFrame` schema extension not yet designed. 16 new tests including privacy boundary verification. Triggered by Reed (Science) improvement proposals.
