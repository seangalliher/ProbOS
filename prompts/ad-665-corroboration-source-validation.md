# AD-665: Corroboration Source Validation

**Status:** Ready for builder (depends on AD-663 for producer wiring; this prompt builds consumer-side validation assuming fields are populated)
**Issue:** #343
**Scope:** OSS (`src/probos/cognitive/social_verification.py`, `src/probos/config.py`, `tests/test_social_verification.py`)

## Context

AD-662 added provenance metadata fields to `AnchorFrame` (`source_origin_id`, `artifact_version`, `anomaly_window_id`) and a binary `_share_artifact_ancestry()` check. Current limitation: the check is exact-match only (`source_origin_id` equality). Reed (Science) submitted 4 improvement proposals identifying gaps:

1. **Transitive ancestry** — A→B→C chain: if Source A produced Artifact B which produced Artifact C, observations anchored to B and C share ancestry but have different `source_origin_id` values. Current binary check misses this.
2. **Version-aware comparison** — Same `source_origin_id` but different `artifact_version` may represent genuinely independent observations if the artifact changed materially between versions.
3. **Provenance validation reporting** — No structured output about *why* corroboration was discounted. Agents (and diagnostics) can't inspect the reasoning.
4. **Configurable similarity threshold** — Hard-coded binary match doesn't support tunable strictness.

## Implementation

### 1. Add `ProvenanceChain` dataclass to `src/probos/cognitive/social_verification.py`

Add after the existing `CascadeRiskResult` dataclass (around line 54):

```python
@dataclass(frozen=True)
class ProvenanceChain:
    """AD-665: Ancestry chain for a single episode's anchor provenance."""
    episode_id: str
    source_origin_id: str
    artifact_version: str
    anomaly_window_id: str
```

### 2. Add `ProvenanceValidationResult` dataclass

Add after `ProvenanceChain`:

```python
@dataclass(frozen=True)
class ProvenanceValidationResult:
    """AD-665: Outcome of provenance-based independence validation."""
    total_pairs_checked: int
    independent_pairs: int
    shared_ancestry_pairs: int
    discounted_pairs: int  # Same origin, different version
    provenance_independence_score: float  # 0.0-1.0
    ancestry_details: list[dict[str, Any]]  # Per-pair breakdown
```

### 3. Add config fields to `SocialVerificationConfig` in `src/probos/config.py`

Add to the existing `SocialVerificationConfig` class (around line 629), after the `anomaly_window_discount` field:

```python
    # Provenance validation (AD-665)
    provenance_version_discount: float = 0.7  # Weight for same-origin-different-version pairs (0.0=reject, 1.0=full independence)
    provenance_chain_max_depth: int = 3  # Max transitive ancestry hops to check
    provenance_validation_enabled: bool = True  # Master toggle for AD-665 validation
```

### 4. Implement `validate_provenance_independence()` function

Add as a module-level function in `social_verification.py`, after the existing `compute_anchor_independence()` function (around line 175):

```python
def validate_provenance_independence(
    episodes: list[Any],
    *,
    version_discount: float = 0.7,
    anomaly_discount: float = 0.5,
) -> ProvenanceValidationResult:
```

Logic:
- Iterate all unique pairs of episodes (same pattern as `compute_anchor_independence()`)
- For each pair, extract `AnchorFrame` provenance fields via `getattr` (defensive, same pattern as existing code)
- Classification per pair:
  - **Independent**: Different `source_origin_id` (or either is empty) AND not in same anomaly window
  - **Shared ancestry**: Same non-empty `source_origin_id` AND same `artifact_version` → count as `shared_ancestry_pairs`, weight = 0.0
  - **Discounted**: Same non-empty `source_origin_id` BUT different `artifact_version` → count as `discounted_pairs`, weight = `version_discount`
  - **Anomaly window**: Either episode has `anomaly_window_id` → apply `anomaly_discount` multiplier on top of other classification
- Compute `provenance_independence_score` = weighted sum / total pairs (same formula structure as existing `compute_anchor_independence()`)
- Build `ancestry_details` list with one dict per non-independent pair: `{"episode_a": id_a, "episode_b": id_b, "reason": str, "weight": float}`
- Return `ProvenanceValidationResult`

### 5. Wire `validate_provenance_independence()` into `check_corroboration()`

In `SocialVerificationService.check_corroboration()` (line 198), after the existing `compute_anchor_independence()` call (line 234):

1. If `self._config.provenance_validation_enabled`:
   - Call `validate_provenance_independence(matching_episodes, version_discount=self._config.provenance_version_discount, anomaly_discount=self._config.anomaly_window_discount)`
   - Use `min(independence, provenance_result.provenance_independence_score)` as the effective independence score
   - This is conservative: the stricter of the two checks wins
2. If disabled, behavior is unchanged (existing `compute_anchor_independence()` score used as-is)

### 6. Wire into `check_cascade_risk()`

In `check_cascade_risk()` (line 355), after the existing `compute_anchor_independence()` call (line 421):

1. Same pattern as above — if enabled, compute provenance validation and use `min()` of both scores
2. Pass the effective score to the existing risk classification logic

### 7. Add provenance details to `CorroborationResult.anchor_summary`

Extend the `anchor_summary` dict construction (around line 310) to include:
- `"provenance_validation"`: The `ProvenanceValidationResult` as a dict (use `dataclasses.asdict()`) when provenance validation was run, else `None`

### 8. Emit `CORROBORATION_PROVENANCE_VALIDATED` event

Add a new `EventType` member in `src/probos/events.py`:

```python
CORROBORATION_PROVENANCE_VALIDATED = "corroboration_provenance_validated"
```

Emit after provenance validation completes in `check_corroboration()` when any shared ancestry was detected (`shared_ancestry_pairs > 0 or discounted_pairs > 0`):

```python
if self._emit_event and provenance_result.shared_ancestry_pairs + provenance_result.discounted_pairs > 0:
    self._emit_event(EventType.CORROBORATION_PROVENANCE_VALIDATED.value, {
        "requesting_agent": requesting_agent_id,
        "provenance_independence_score": provenance_result.provenance_independence_score,
        "shared_ancestry_pairs": provenance_result.shared_ancestry_pairs,
        "discounted_pairs": provenance_result.discounted_pairs,
        "total_pairs": provenance_result.total_pairs_checked,
    })
```

### 9. Tests — `tests/test_social_verification.py`

Add a new test class `TestProvenanceValidation` after the existing `TestSourceProvenance` class (around line 740). Tests:

1. **`test_provenance_all_independent`** — Episodes with different `source_origin_id` → score 1.0, 0 shared pairs
2. **`test_provenance_shared_ancestry_same_version`** — Same origin + same version → score 0.0, shared pair counted
3. **`test_provenance_shared_ancestry_different_version`** — Same origin + different version → score = `version_discount`, discounted pair counted
4. **`test_provenance_mixed_pairs`** — 3 episodes: A-B independent, B-C shared ancestry, A-C discounted → verify weighted score
5. **`test_provenance_empty_origin_treated_as_independent`** — Empty `source_origin_id` on either side → independent (defensive)
6. **`test_provenance_anomaly_window_compounds_discount`** — Same origin + anomaly window → both discounts applied multiplicatively
7. **`test_provenance_disabled_config`** — `provenance_validation_enabled=False` → no provenance check, existing independence score used alone
8. **`test_provenance_wired_into_corroboration`** — Integration: shared ancestry episodes → effective independence score is `min()` of both checks
9. **`test_provenance_wired_into_cascade`** — Integration: shared ancestry in cascade check → lower independence → higher risk
10. **`test_provenance_event_emitted_on_shared_ancestry`** — Verify `CORROBORATION_PROVENANCE_VALIDATED` event emitted with correct payload
11. **`test_provenance_no_event_when_all_independent`** — No event emitted when all pairs are independent
12. **`test_provenance_result_in_anchor_summary`** — `CorroborationResult.anchor_summary["provenance_validation"]` populated
13. **`test_provenance_single_episode_returns_trivial`** — 0 or 1 episode → score 1.0, 0 pairs checked

Use the existing `_make_episode()` and `_rich_anchors()` helpers. Create episodes with provenance fields via `_rich_anchors()` extended or by constructing `AnchorFrame` directly with provenance fields.

## Files Changed

| File | Change |
|------|--------|
| `src/probos/cognitive/social_verification.py` | `ProvenanceChain`, `ProvenanceValidationResult`, `validate_provenance_independence()`, wiring in `check_corroboration()` and `check_cascade_risk()` |
| `src/probos/config.py` | 3 new fields in `SocialVerificationConfig` |
| `src/probos/events.py` | `CORROBORATION_PROVENANCE_VALIDATED` event type |
| `tests/test_social_verification.py` | 13 new tests in `TestProvenanceValidation` |

## Tracker Updates

- `PROGRESS.md` — Update AD-665 from PLANNED to COMPLETE
- `docs/development/roadmap.md` — Update AD-665 status to Complete
- `DECISIONS.md` — Add: "AD-665: Provenance-based independence validation uses conservative min() of existing spatial/temporal independence and new provenance check. Version-different-same-origin pairs get configurable discount (default 0.7) rather than binary accept/reject."
