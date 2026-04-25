# AD-662: Corroboration Source Provenance Validation

**Ticket:** AD-662 (GitHub Issue #331)  
**Status:** Ready for Builder  
**Depends on:** AD-567f (Social Verification Protocol — COMPLETE)  
**Prior art:** AD-567a (Anchor Framework), AD-567c (Anchor Quality), AD-567d (Anchor Provenance Composition), AD-540 (Knowledge Source Attribution), BF-204 (Deterministic Grounding)

---

## Motivation

AD-567f's `SocialVerificationService` detects cascade confabulation by checking if corroborating agents have **independently anchored** observations. The independence check examines spatiotemporal separation (duty_cycle_id, channel_id, thread_id, time separation) but does NOT check **artifact ancestry**.

**The gap:** Two agents can observe the same corrupted data artifact at different times, from different channels, and pass all independence checks — yet their "corroboration" traces back to a single source. This is analogous to intelligence analysis circular reporting: two reports from different analysts, both sourcing the same fabricated document, appear independent but are not.

**Example (BF-226/227):** During queue pressure, the system generated duplicate artifact versions. Multiple agents observed these artifacts independently (different duty cycles, different channels) and their observations correctly passed spatiotemporal independence checks. However, the artifacts shared the same corrupted ancestry — the corroboration was false.

---

## What This Does

Extends `AnchorFrame` and `SocialVerificationService` with source provenance metadata:

1. **AnchorFrame provenance fields** — Track which data artifact an observation derives from
2. **Ancestry check** — Before scoring two observations as independent, verify they don't share a common source artifact
3. **Anomaly window detection** — Flag observations that cluster within a known anomaly window
4. **Updated independence scoring** — Factor provenance into `anchor_independence_score`

---

## What This Does NOT Change

- **Privacy model** — No episode content is exposed. Provenance metadata (origin IDs) is aggregate, not content.
- **anchor_provenance.py** — Dream consolidation provenance composition is unchanged. That module composes provenance forward into derivative artifacts; AD-662 checks provenance backward for independence.
- **anchor_quality.py** — Johnson-weighted confidence scoring is unchanged. Provenance is a new orthogonal dimension, not a replacement for anchor quality.
- **CorroborationResult / CascadeRiskResult dataclass fields** — Existing fields and their semantics are unchanged. New provenance fields are additive.
- **BridgeAlertService** — Cascade alert emission unchanged.
- **evaluate.py BF-204 grounding check** — Separate mechanism, not modified.
- **Standing Orders / federation.md** — Source reliability hierarchy unchanged.
- **AnchorFrame producer sites** — AD-662 adds the validation infrastructure (consumer-side). Populating `source_origin_id`, `artifact_version`, and `anomaly_window_id` at AnchorFrame construction sites (proactive loop, ward room handlers, dream consolidation) is out of scope — tracked as AD-663. Until producers populate the new fields, all production episodes have empty provenance fields and the ancestry guard is a no-op. AD-662 alone does not close the BF-226/227 production gap; it provides the infrastructure that AD-663 will activate.
- **Anomaly window producer** — Determining WHEN to tag an observation as occurring during an anomaly window (queue pressure detector, LLM degradation monitor) is producer-side work, also deferred to AD-663.

---

### 1. Extend AnchorFrame with Source Provenance Fields

**File:** `src/probos/types.py`  
**Location:** `AnchorFrame` dataclass (around line 351)

Add a new `# SOURCE PROVENANCE` section after the existing `# EVIDENTIAL` section:

```python
# Current code (around line 377):
    # EVIDENTIAL — what corroborates this?
    thread_id: str = ""              # Ward Room thread ID for cross-reference
    event_log_window: float = 0.0    # Timestamp range for EventLog cross-verification
```

Add after that block:

```python
    # SOURCE PROVENANCE — where did the observed data originate? (AD-662)
    source_origin_id: str = ""       # ID of the root data artifact that generated this observation
    artifact_version: str = ""       # Version/hash of the artifact observed (detects same-version dupes)
    anomaly_window_id: str = ""      # If observed during a known anomaly window, its ID
```

**Design rationale:** Three fields, not a nested object, to keep AnchorFrame flat and frozen. `source_origin_id` is the root artifact (e.g., the original Ward Room post ID, the duty cycle output ID, the event that started the chain). `artifact_version` is a fingerprint of the specific version observed (so two agents observing the same artifact at different times can be detected). `anomaly_window_id` links to a known anomaly period (queue pressure, LLM degradation) if the observation occurred during one.

All fields default to `""` (empty string) — backward compatible with existing AnchorFrame instances.

---

### 1a. Add Config Field for Anomaly Window Discount

**File:** `src/probos/config.py`  
**Location:** `SocialVerificationConfig` class (around line 629)

Add after the existing `cascade_cooldown_seconds` field (around line 640):

```python
    # Provenance (AD-662)
    anomaly_window_discount: float = 0.5  # 0.0-1.0: weight discount for anomaly window pairs
```

**Calibration signal:** Ratio of anomaly-window cascades that produce false-positive vs true-positive cascade alerts. If false positives dominate, raise toward 1.0 (no discount); if true positives are missed, lower toward 0.0 (full rejection).

---

### 2. Add Ancestry Check Function

**File:** `src/probos/cognitive/social_verification.py`  
**Location:** After `_time_separated()` function (around line 95), before `compute_anchor_independence()`

Add new function:

```python
def _share_artifact_ancestry(anchors_a: Any, anchors_b: Any) -> bool:
    """Check if two anchor frames share source artifact ancestry (AD-662).

    Two observations sharing the same source_origin_id are NOT independent —
    they derive from the same root data, regardless of spatiotemporal separation.
    Same source_origin_id AND same artifact_version is a stronger signal
    (same artifact, same version). artifact_version alone is NOT sufficient
    because version strings may collide across unrelated artifacts.

    AD-662 preserves existing behavior for None/missing anchors — episodes
    without anchors are not given the ancestry guard. A future AD may tighten this.
    """
    if anchors_a is None or anchors_b is None:
        return False  # Can't determine ancestry without anchors — don't block

    origin_a = getattr(anchors_a, "source_origin_id", "") or ""
    origin_b = getattr(anchors_b, "source_origin_id", "") or ""

    # Same source origin = shared ancestry
    if origin_a and origin_b and origin_a == origin_b:
        return True

    return False


def _in_anomaly_window(anchors: Any) -> bool:
    """Check if an observation occurred during a known anomaly window (AD-662).

    Observations during anomaly windows get reduced independence weight,
    not outright rejection — the anomaly may not have affected this specific
    observation.
    """
    if anchors is None:
        return False
    return bool(getattr(anchors, "anomaly_window_id", "") or "")
```

---

### 3. DO NOT Modify `_are_independently_anchored()`

`_are_independently_anchored()` checks spatiotemporal separation only. Ancestry is an orthogonal concern. The ancestry veto is applied at the **scoring level** in `compute_anchor_independence()` and the `independent_count` loop in `check_corroboration()` (Sections 4 and 5) — this is architecturally cleaner because `_time_separated()` also bypasses `_are_independently_anchored()` via an `OR` condition, so the ancestry guard must live at the same level as both checks.

**No changes to `_are_independently_anchored()`.**

**Callers of `_are_independently_anchored` (2 internal):** Lines 115 and 214 within `social_verification.py`. No external callers.

---

### 4. Integrate Anomaly Window into Independence Scoring

**File:** `src/probos/cognitive/social_verification.py`  
**Location:** `compute_anchor_independence()` function (around line 98)

**Current code:**

```python
def compute_anchor_independence(episodes: list[Any]) -> float:
    """Compute anchor independence score for a set of episodes.

    Returns 0.0-1.0: ratio of independently anchored episode pairs
    to total episode pairs.
    """
    if len(episodes) < 2:
        return 0.0

    total_pairs = 0
    independent_pairs = 0

    for i in range(len(episodes)):
        for j in range(i + 1, len(episodes)):
            total_pairs += 1
            a = getattr(episodes[i], "anchors", None)
            b = getattr(episodes[j], "anchors", None)
            if _are_independently_anchored(a, b) or _time_separated(episodes[i], episodes[j]):
                independent_pairs += 1

    return independent_pairs / total_pairs if total_pairs > 0 else 0.0
```

**Replace with:**

```python
def compute_anchor_independence(
    episodes: list[Any],
    anomaly_discount: float = 0.5,
) -> float:
    """Compute anchor independence score for a set of episodes.

    Returns 0.0-1.0: weighted ratio of independently anchored episode pairs
    to total episode pairs (AD-662).

    AD-662 additions:
    - Pairs sharing artifact ancestry (same source_origin_id) are NOT
      independent, regardless of spatiotemporal separation or time gap.
    - Pairs where either episode occurred during an anomaly window
      contribute ``anomaly_discount`` weight (default 0.5x) to the score.
    """
    if len(episodes) < 2:
        return 0.0

    total_weight = 0.0
    independent_weight = 0.0

    for i in range(len(episodes)):
        for j in range(i + 1, len(episodes)):
            a = getattr(episodes[i], "anchors", None)
            b = getattr(episodes[j], "anchors", None)

            # AD-662: Discount pairs involving anomaly window observations
            pair_weight = 1.0
            if _in_anomaly_window(a) or _in_anomaly_window(b):
                pair_weight = anomaly_discount

            total_weight += pair_weight

            # AD-662: Shared ancestry is an absolute veto — overrides both
            # spatiotemporal independence AND time separation
            if _share_artifact_ancestry(a, b):
                pass  # Not independent, regardless of other signals
            elif _are_independently_anchored(a, b) or _time_separated(episodes[i], episodes[j]):
                independent_weight += pair_weight

    return independent_weight / total_weight if total_weight > 0 else 0.0
```

**Design rationale:** Anomaly window observations are not rejected outright — an agent may have observed something genuine during an anomaly period. Instead, their contribution to independence scoring is discounted. The `anomaly_discount` parameter defaults to 0.5 and is passed from `SocialVerificationConfig.anomaly_window_discount` at call sites within `SocialVerificationService`.

**Callers of `compute_anchor_independence` (4 external + 2 internal):**
- `src/probos/cognitive/behavioral_metrics.py` (2 call sites, around lines 568/595) — calls without `anomaly_discount` kwarg, uses default 0.5, backward compatible
- `src/probos/knowledge/records_store.py` (2 call sites, around lines 554/582) — same, backward compatible
- `src/probos/cognitive/dreaming.py` (3 call sites, around lines 802/819/971) — same, backward compatible
- `src/probos/ward_room/thread_echo.py` (1 call site, around line 136) — same, backward compatible
- `social_verification.py` internal: `check_corroboration()` line 177 and `check_cascade_risk()` line 346 — update these two call sites to pass `anomaly_discount=self._config.anomaly_window_discount`

All external callers use positional `episodes` only; the new kwarg `anomaly_discount` has a default, so no external changes needed.

---

### 5. Add Provenance Summary to CorroborationResult anchor_summary

**File:** `src/probos/cognitive/social_verification.py`  
**Location:** `check_corroboration()` method, in the anchor summary construction (around line 238)

**Current code (around line 238):**

```python
        anchor_summary: dict[str, Any] = {
            "shared_channels": sorted(channels),
            "shared_departments": matching_departments,
            "unique_participants": sorted(all_participants),
            "time_span_seconds": time_span,
        }
```

**Replace with:**

```python
        # AD-662: Collect provenance metadata
        origin_ids: set[str] = set()
        anomaly_flagged = 0
        for ep in qualified:
            anchors = getattr(ep, "anchors", None)
            if anchors:
                oid = getattr(anchors, "source_origin_id", "") or ""
                if oid:
                    origin_ids.add(oid)
                if _in_anomaly_window(anchors):
                    anomaly_flagged += 1

        anchor_summary: dict[str, Any] = {
            "shared_channels": sorted(channels),
            "shared_departments": matching_departments,
            "unique_participants": sorted(all_participants),
            "time_span_seconds": time_span,
            "unique_source_origins": len(origin_ids),  # AD-662
            "anomaly_window_episodes": anomaly_flagged,  # AD-662
        }
```

**Note:** Only the *count* of unique origins is exposed, not the IDs themselves — consistent with the privacy principle (metadata counts, not content).

---

### 5a. Apply Ancestry Guard to `check_corroboration` Independent Count Loop

**File:** `src/probos/cognitive/social_verification.py`  
**Location:** `check_corroboration()` method, `independent_count` inner loop (around line 206)

The same `_are_independently_anchored() or _time_separated()` pattern appears here. Apply the same ancestry guard.

**Current code (around line 206):**

```python
        # Count independent anchors
        independent_count = 0
        if len(qualified) >= 2:
            # Count episodes that are independent from at least one other
            for i, ep in enumerate(qualified):
                for j, other in enumerate(qualified):
                    if i == j:
                        continue
                    a = getattr(ep, "anchors", None)
                    b = getattr(other, "anchors", None)
                    if _are_independently_anchored(a, b) or _time_separated(ep, other):
                        independent_count += 1
                        break
```

**Replace with:**

```python
        # Count independent anchors
        independent_count = 0
        if len(qualified) >= 2:
            # Count episodes that are independent from at least one other
            for i, ep in enumerate(qualified):
                for j, other in enumerate(qualified):
                    if i == j:
                        continue
                    a = getattr(ep, "anchors", None)
                    b = getattr(other, "anchors", None)
                    # AD-662: Shared ancestry vetoes independence
                    if _share_artifact_ancestry(a, b):
                        continue
                    if _are_independently_anchored(a, b) or _time_separated(ep, other):
                        independent_count += 1
                        break
```

**Semantic note for Section 5a:** An episode is considered "independently counted" if it has at least one peer with neither shared ancestry NOR spatiotemporal collision. This means an episode adjacent to one corrupted twin can still "count" if it has a clean twin elsewhere. This matches `compute_anchor_independence` semantics where shared-ancestry pairs score 0 but other pairs can still score positively. The asymmetry is intentional — a single corrupted source taints only the specific pairs involving it, not the entire episode.

---

### 5b. Update Internal Call Sites for `compute_anchor_independence`

**File:** `src/probos/cognitive/social_verification.py`

Update the two internal call sites to pass the config-driven discount:

1. In `check_corroboration()` (around line 177):

**Current:** `independence = compute_anchor_independence(qualified)`  
**Replace:** `independence = compute_anchor_independence(qualified, anomaly_discount=self._config.anomaly_window_discount)`

2. In `check_cascade_risk()` (around line 346):

**Current:** `independence = compute_anchor_independence(matched_episodes)`  
**Replace:** `independence = compute_anchor_independence(matched_episodes, anomaly_discount=self._config.anomaly_window_discount)`

**File:** `src/probos/cognitive/social_verification.py`

---

### 6. Tests

**File:** `tests/test_social_verification.py`

Add the following imports to the existing import block (around line 15):

```python
from probos.cognitive.social_verification import (
    CascadeRiskResult,
    CorroborationResult,
    SocialVerificationService,
    compute_anchor_independence,
    _are_independently_anchored,
    _share_artifact_ancestry,
    _in_anomaly_window,
)
```

Add a new test class at the END of the file, after `TestEvents` (around line 564):

```python
# ===========================================================================
# 6. Source Provenance tests (AD-662) (11)
# ===========================================================================

class TestSourceProvenance:
    """Tests for AD-662: Corroboration Source Provenance Validation."""

    # --- _share_artifact_ancestry ---

    def test_shared_origin_detected(self):
        """Same source_origin_id = shared ancestry."""
        a = AnchorFrame(source_origin_id="artifact-X", duty_cycle_id="dc-1")
        b = AnchorFrame(source_origin_id="artifact-X", duty_cycle_id="dc-2")
        assert _share_artifact_ancestry(a, b) is True

    def test_different_origin_independent(self):
        """Different source_origin_id = no shared ancestry."""
        a = AnchorFrame(source_origin_id="artifact-X")
        b = AnchorFrame(source_origin_id="artifact-Y")
        assert _share_artifact_ancestry(a, b) is False

    def test_shared_version_alone_not_sufficient(self):
        """Same artifact_version WITHOUT same origin = NOT shared ancestry.
        Version strings may collide across unrelated artifacts."""
        a = AnchorFrame(source_origin_id="artifact-X", artifact_version="v1-abc123")
        b = AnchorFrame(source_origin_id="artifact-Y", artifact_version="v1-abc123")
        assert _share_artifact_ancestry(a, b) is False

    def test_shared_origin_with_version(self):
        """Same origin AND same version = shared ancestry (strongest signal)."""
        a = AnchorFrame(source_origin_id="artifact-X", artifact_version="v1-abc123")
        b = AnchorFrame(source_origin_id="artifact-X", artifact_version="v1-abc123")
        assert _share_artifact_ancestry(a, b) is True

    def test_empty_provenance_no_ancestry(self):
        """Empty provenance fields = no ancestry detected (don't block)."""
        a = AnchorFrame(duty_cycle_id="dc-1")
        b = AnchorFrame(duty_cycle_id="dc-2")
        assert _share_artifact_ancestry(a, b) is False

    def test_none_anchors_no_ancestry(self):
        """None anchors = no ancestry (can't determine)."""
        assert _share_artifact_ancestry(None, None) is False
        assert _share_artifact_ancestry(AnchorFrame(), None) is False

    # --- _in_anomaly_window ---

    def test_anomaly_window_detected(self):
        """Non-empty anomaly_window_id = in anomaly window."""
        a = AnchorFrame(anomaly_window_id="aw-001")
        assert _in_anomaly_window(a) is True

    def test_no_anomaly_window(self):
        """Empty anomaly_window_id = not in anomaly window."""
        a = AnchorFrame()
        assert _in_anomaly_window(a) is False

    # --- Integration: ancestry vetoes spatiotemporal independence ---

    def test_independence_vetoed_by_shared_ancestry(self):
        """Different duty cycles + channels BUT same origin = NOT independent."""
        a = AnchorFrame(
            duty_cycle_id="dc-1", channel_id="ch-1",
            source_origin_id="artifact-X",
        )
        b = AnchorFrame(
            duty_cycle_id="dc-2", channel_id="ch-2",
            source_origin_id="artifact-X",
        )
        # Timestamps within 60s so time_separated doesn't bypass the veto
        ep1 = _make_episode(agent_ids=["A"], anchors=a, timestamp=100.0, ep_id="ep-1")
        ep2 = _make_episode(agent_ids=["B"], anchors=b, timestamp=110.0, ep_id="ep-2")
        score = compute_anchor_independence([ep1, ep2])
        assert score == 0.0

    def test_independence_granted_with_different_ancestry(self):
        """Different duty cycles + different origin = independent."""
        a = AnchorFrame(
            duty_cycle_id="dc-1", channel_id="ch-1",
            source_origin_id="artifact-X",
        )
        b = AnchorFrame(
            duty_cycle_id="dc-2", channel_id="ch-2",
            source_origin_id="artifact-Y",
        )
        ep1 = _make_episode(agent_ids=["A"], anchors=a, timestamp=100.0, ep_id="ep-1")
        ep2 = _make_episode(agent_ids=["B"], anchors=b, timestamp=110.0, ep_id="ep-2")
        score = compute_anchor_independence([ep1, ep2])
        assert score == 1.0

    # --- Anomaly window scoring discount ---

    def test_anomaly_window_discounts_independence_score(self):
        """Episodes in anomaly window get discounted independence contribution."""
        # Two normal episodes that are independently anchored
        ep_normal_1 = _make_episode(
            agent_ids=["A"], ep_id="ep-1",
            anchors=AnchorFrame(duty_cycle_id="dc-1", channel_id="ch-1"),
            timestamp=100.0,
        )
        ep_normal_2 = _make_episode(
            agent_ids=["B"], ep_id="ep-2",
            anchors=AnchorFrame(duty_cycle_id="dc-2", channel_id="ch-2"),
            timestamp=110.0,
        )
        # An anomaly episode that is DEPENDENT (same duty cycle, close timestamp)
        ep_anomaly = _make_episode(
            agent_ids=["C"], ep_id="ep-3",
            anchors=AnchorFrame(
                duty_cycle_id="dc-1", channel_id="ch-1",
                anomaly_window_id="aw-001",
            ),
            timestamp=105.0,
        )

        # Without anomaly episode: 1 pair (ep1-ep2), independent → score = 1.0
        score_clean = compute_anchor_independence([ep_normal_1, ep_normal_2])
        assert score_clean == 1.0

        # With anomaly episode: 3 pairs
        # ep1-ep2: independent, weight=1.0, contributes 1.0
        # ep1-ep3: same duty_cycle, <60s → dependent, weight=0.5, contributes 0
        # ep2-ep3: different duty_cycle → independent, weight=0.5, contributes 0.5
        # total_weight = 1.0 + 0.5 + 0.5 = 2.0
        # independent_weight = 1.0 + 0.0 + 0.5 = 1.5
        # score = 1.5 / 2.0 = 0.75
        score_with_anomaly = compute_anchor_independence([ep_normal_1, ep_normal_2, ep_anomaly])
        assert score_with_anomaly == 0.75
```

Also update the existing `TestCorroboration` class. Add one provenance-aware test after `test_corroboration_threshold_boundary`:

```python
    @pytest.mark.asyncio
    async def test_corroboration_shared_ancestry_reduces_independence(self):
        """Two agents with same source_origin_id should have low independence."""
        # Use _rich_anchors() to ensure episodes pass confidence gate (0.3),
        # then override source_origin_id to test ancestry check
        anchors_1 = dataclasses.replace(
            _rich_anchors(1), source_origin_id="shared-artifact-001",
        )
        anchors_2 = dataclasses.replace(
            _rich_anchors(2), source_origin_id="shared-artifact-001",
        )
        eps = [
            _make_episode(agent_ids=["B"], anchors=anchors_1, timestamp=100.0, ep_id="ep-1"),
            _make_episode(agent_ids=["C"], anchors=anchors_2, timestamp=110.0, ep_id="ep-2"),
        ]
        svc = _make_service(episodes=eps)
        result = await svc.check_corroboration("agent-A", "test claim")
        # Despite different duty_cycles and channels, shared ancestry → not independent
        assert result.anchor_independence_score == 0.0
```

Add one provenance-aware test to `TestCascadeRisk` after `test_cascade_same_thread_dependent`:

```python
    @pytest.mark.asyncio
    async def test_cascade_shared_ancestry_flags_risk(self):
        """Peer matches sharing artifact ancestry should flag cascade risk."""
        # Use _rich_anchors() base for confidence gate, override origin
        anchors = dataclasses.replace(
            _rich_anchors(1), source_origin_id="corrupted-artifact-001",
        )
        eps = [
            _make_episode(agent_ids=["B"], ep_id="ep-B", anchors=anchors, timestamp=100.0),
            _make_episode(agent_ids=["C"], ep_id="ep-C", anchors=anchors, timestamp=110.0),
            _make_episode(agent_ids=["A"], ep_id="ep-A", anchors=anchors, timestamp=120.0),
        ]
        svc = _make_service(episodes=eps)
        peer_matches = [
            {"author_id": "B", "author_callsign": "Bravo", "timestamp": 100.0},
            {"author_id": "C", "author_callsign": "Charlie", "timestamp": 110.0},
        ]
        result = await svc.check_cascade_risk(
            "A", "Alpha", "post body", "ch-1", peer_matches=peer_matches,
        )
        assert result is not None
        # Shared ancestry → not independent → cascade risk flagged
        assert result.anchor_independence_score == 0.0
```

**Total new tests: 13** (11 in TestSourceProvenance + 1 in TestCorroboration + 1 in TestCascadeRisk).

---

### 7. Existing Test Impact

The following existing tests reference `AnchorFrame` or `compute_anchor_independence` and will continue to pass because all new fields default to `""`:

- All 28 tests in `test_social_verification.py` — backward compatible (no provenance fields set = no ancestry match = same behavior as before)
- Tests in `test_anchor_quality.py` — `compute_anchor_confidence()` ignores provenance fields (separate dimension)
- Tests in `test_anchor_provenance.py` — dream consolidation provenance unaffected
- `test_ad583_wrong_convergence.py` — calls `compute_anchor_independence` directly with `SimpleNamespace` objects (no provenance fields, `getattr` defaults to `""`, ancestry guard is no-op). Numeric assertions (e.g., `score < 0.3`, `score > 0.3`) unchanged.
- `test_behavioral_metrics.py` — patches `compute_anchor_independence` as a mock. Unaffected by behavioral changes.

No existing test assertion updates are required.

---

## Verification

```bash
# After each section:
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_social_verification.py -v

# Full suite after all sections complete:
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

### PROGRESS.md
Add under the appropriate section:
```
- AD-662 — Corroboration Source Provenance Validation — CLOSED
```

### docs/development/roadmap.md
Add/update the AD-662 row to Closed status.

### DECISIONS.md
Append to Era V — Civilization:

```markdown
### AD-662 — Corroboration Source Provenance Validation

**Date:** 2026-04-23
**Status:** Complete
**Depends on:** AD-567f (Social Verification Protocol)

**Decision:** Extend SocialVerificationService with source provenance tracking. Three new AnchorFrame fields (source_origin_id, artifact_version, anomaly_window_id) enable ancestry-based independence checks. Two observations sharing the same source artifact are NOT independently anchored, regardless of spatiotemporal separation. Anomaly window observations contribute at config-driven discounted weight (default 0.5) to independence scoring (log-and-degrade, not reject). `artifact_version` alone does not trigger shared ancestry — only `source_origin_id` match does — to avoid false positives from version string collisions. Triggered by BF-226/227 where queue-pressure-generated artifact versions appeared to corroborate each other but shared corrupted ancestry. AD-662 is infrastructure-only (consumer-side validation); AD-663 wires the producers to populate provenance fields at AnchorFrame construction sites. 13 new tests.
```
