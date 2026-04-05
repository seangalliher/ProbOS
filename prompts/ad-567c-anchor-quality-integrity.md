# AD-567c: Anchor Quality & Integrity

**Absorbs:** AD-567e (Anchor Drift Detection)
**Depends:** AD-567a (Episode Anchor Metadata — COMPLETE), AD-567b (Anchor-Aware Recall — in build)
**Prior art:** Johnson & Raye (1981) reality monitoring, Johnson SMF (1993), CAST (Ma 2026), RPMS (Yuan 2026), Video-EM (Wang 2025)
**Crew observation:** Echo/Meridian thread 92719789 (2026-04-03) — "what looks like cognitive drift might actually be healthy specialization"

---

## Context

AD-567a added `AnchorFrame` to episodes (10 fields across 5 dimensions). AD-567b (in build) adds salience-weighted recall that uses `anchor_completeness` as one scoring signal. But anchor completeness is a blunt 0-or-1 per field — it doesn't weight dimensions by their diagnostic value, doesn't aggregate per-agent profiles, and doesn't feed into SIF, Counselor, or drift classification.

AD-567c delivers four capabilities:
1. **Anchor confidence scoring** — weighted per-dimension groundedness (0.0–1.0)
2. **Per-agent anchor profiles** — CAST-inspired statistical profiles for Counselor diagnostics
3. **SIF anchor integrity checks** — verify anchors against real ship events
4. **Drift classification** — distinguish healthy specialization from concerning drift

---

## Scope

### 1. Anchor Confidence Scoring

**File: `src/probos/cognitive/anchor_quality.py`** (NEW)

Create `compute_anchor_confidence(anchors: AnchorFrame | None) -> float`:

Johnson & Raye (1981) finding: real memories have more contextual/perceptual detail (when/where/who); imagined memories rely on cognitive operations (how). Weight contextual dimensions higher for confabulation detection.

**Dimension weights** (must sum to 1.0):

| Dimension | Fields | Weight | Rationale |
|-----------|--------|--------|-----------|
| Temporal | `duty_cycle_id`, `watch_section` | 0.25 | When — strong reality marker |
| Spatial | `channel`, `channel_id`, `department` | 0.25 | Where — strong reality marker |
| Social | `participants`, `trigger_agent` | 0.25 | Who — strong reality marker |
| Causal | `trigger_type` | 0.15 | Why/How — weaker per Johnson |
| Evidential | `thread_id`, `event_log_window` | 0.10 | Corroboration — supplementary |

**Per-dimension scoring:**
- Dimension with ALL fields filled = 1.0
- Dimension with SOME fields filled = proportion (e.g., 1 of 3 spatial fields = 0.33)
- Dimension with no fields filled = 0.0

**"Filled" rules:**
- `str` field: non-empty (`!= ""`)
- `list[str]` field (`participants`): non-empty (`len > 0`)
- `float` field (`event_log_window`): non-zero (`> 0.0`)

**Result:** `confidence = sum(dimension_weight * dimension_score for each dimension)`. Range [0.0, 1.0]. `anchors=None` → 0.0.

**Configuration** — add to `MemoryConfig` in `config.py`:
```python
# AD-567c: Anchor confidence
anchor_dimension_weights: dict[str, float] = field(default_factory=lambda: {
    "temporal": 0.25,
    "spatial": 0.25,
    "social": 0.25,
    "causal": 0.15,
    "evidential": 0.10,
})
anchor_confidence_gate: float = 0.3  # RPMS: suppress below this from default recall
```

### 2. RPMS Confidence Gating in Recall

**File: `src/probos/cognitive/episodic.py`**

Modify `recall_weighted()` (added by AD-567b) to apply confidence gating:
- After computing `RecallScore` for each candidate, filter out episodes where `anchor_completeness < anchor_confidence_gate` (default 0.3)
- Filtered episodes are NOT deleted — still accessible via explicit `recall_for_agent()` which bypasses gating
- Replace the simple `anchor_completeness` field in `RecallScore` with the weighted `anchor_confidence` from `compute_anchor_confidence()`

**Update `RecallScore` in `types.py`:**
- Rename field `anchor_completeness` → `anchor_confidence` (or add `anchor_confidence` if 567b used a different name; check what 567b actually created)

### 3. Per-Agent Anchor Profiles (CAST)

**File: `src/probos/cognitive/anchor_quality.py`**

Create `AnchorProfile` dataclass:
```python
@dataclass
class AnchorProfile:
    agent_id: str
    total_episodes: int
    mean_confidence: float           # average anchor confidence across all episodes
    median_confidence: float
    low_confidence_count: int        # episodes below anchor_confidence_gate
    low_confidence_pct: float        # proportion below gate
    dimension_fill_rates: dict[str, float]  # per-dimension fill rate across all episodes
    weakest_dimension: str           # dimension with lowest fill rate
    strongest_dimension: str         # dimension with highest fill rate
    timestamp: float                 # when profile was computed
```

Create `build_anchor_profile(agent_id: str, episodic_memory: EpisodicMemory) -> AnchorProfile`:
- Fetch all episodes for agent via `recent_for_agent(agent_id, k=100)` (or a new bulk method if needed)
- Compute statistics across all anchors
- This is a batch operation — run during dream cycle or on-demand, not on every recall

**Counselor integration** — add to `CognitiveProfile` in counselor.py:
- New field: `anchor_quality: float = 0.0` (mean confidence from latest profile)
- New field: `weakest_anchor_dimension: str = ""` (for targeted metacognitive coaching)
- Updated during dream Step 11 or Counselor wellness sweep
- Counselor raises concern when `anchor_quality < 0.3` consistently (agent producing ungrounded memories)

### 4. SIF Anchor Integrity Check

**File: `src/probos/sif.py`**

Add `check_anchor_integrity(self) -> SIFCheckResult`:

**Pattern:** Match existing SIF check pattern (synchronous, guard-then-check-then-return).

**What it checks** (sampled, not exhaustive — SIF runs every 5 seconds):
1. **Sample size:** Check last N episodes from a cached recent list (populated asynchronously, checked synchronously). Store `_anchor_check_cache` on the SIF instance, updated periodically.
2. **Anchor presence rate:** What % of recent episodes have non-None anchors? Below 50% → failure (new episodes should always have anchors after AD-567a).
3. **Cross-reference validation (Video-EM):** For episodes with `thread_id`, verify the thread exists in Ward Room. For episodes with `participants`, verify participants are known agents.
4. **Cross-anchor consistency (Video-EM):** Check for impossible states — same agent in both a WR thread and a DM at the same timestamp.

**Constructor change:** Add `episodic_memory` parameter (already exists) + `ward_room` parameter (new, for thread verification). Wire in `startup/structural_services.py`.

**Cache strategy:** SIF checks are sync. Add an async `_refresh_anchor_cache()` method called from the periodic loop BEFORE `run_all_checks()`. Cache stores the last 50 episodes + their anchor data. The sync `check_anchor_integrity()` reads from cache only.

**Add to check tuple in `run_all_checks()`** at end of existing list.

### 5. Drift Classification (Echo/Meridian Insight)

**File: `src/probos/cognitive/drift_detector.py`**

Extend `DriftSignal` with a new field:
```python
drift_type: str = "unclassified"  # "specialization" | "concerning" | "unclassified"
```

**Classification logic** in `DriftDetector._analyze_single()`:

After computing z-score and direction, classify the drift:
1. Fetch the agent's anchor profile (cached, from most recent computation)
2. **High-confidence divergence = specialization:**
   - `direction == "declined"` (score dropped from baseline)
   - BUT agent's `mean_anchor_confidence >= 0.6` (memories are well-grounded)
   - AND the declined test is outside the agent's primary domain (e.g., medical agent declining on code_quality)
   - Classification: `"specialization"` — the agent is developing strengths elsewhere, not losing capability
3. **Low-confidence divergence = concerning:**
   - `direction == "declined"`
   - AND agent's `mean_anchor_confidence < 0.4` (memories are poorly grounded)
   - Classification: `"concerning"` — capability loss correlated with ungrounded memory
4. **Otherwise:** `"unclassified"`

**Determining "primary domain":** Use HebbianRouter weights. The agent's top 3 intent types by Hebbian weight define their domain. If the declining test aligns with top intents, it's concerning. If it's outside their domain, it's specialization.

**Event payload update:** Add `drift_type` to the `QUALIFICATION_DRIFT_DETECTED` event payload.

**Counselor handler update** in `counselor.py` `_on_qualification_drift()`:
- `"specialization"` drift at critical severity → log but do NOT trigger assessment (healthy divergence)
- `"concerning"` drift even at warning severity → trigger assessment + therapeutic DM
- `"unclassified"` → existing behavior (critical triggers assessment, warning logs only)

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/probos/cognitive/anchor_quality.py` | **NEW** — `compute_anchor_confidence()`, `AnchorProfile`, `build_anchor_profile()` |
| `src/probos/types.py` | Update `RecallScore.anchor_completeness` → `anchor_confidence` (if AD-567b created it) |
| `src/probos/config.py` | Add `anchor_dimension_weights`, `anchor_confidence_gate` to `MemoryConfig` |
| `src/probos/cognitive/episodic.py` | RPMS confidence gating in `recall_weighted()`, use weighted confidence instead of simple completeness |
| `src/probos/sif.py` | `check_anchor_integrity()`, `_anchor_check_cache`, cache refresh, new constructor param |
| `src/probos/startup/structural_services.py` | Wire `ward_room` into SIF constructor |
| `src/probos/cognitive/drift_detector.py` | `drift_type` field on `DriftSignal`, classification logic, domain detection via Hebbian |
| `src/probos/cognitive/counselor.py` | `anchor_quality`/`weakest_anchor_dimension` on CognitiveProfile, `_on_qualification_drift()` drift_type handling |
| `src/probos/events.py` | Update `QUALIFICATION_DRIFT_DETECTED` payload spec (add drift_type) |

## Files NOT to Modify

- `episodic.py` existing `recall_for_agent()`, `recent_for_agent()`, `store()` — no changes
- `qualification_tests.py` — confabulation probe stays as-is; anchor confidence feeds into drift detection, not probe scoring
- `guided_reminiscence.py` — no changes (future: correlate confabulation_rate with anchor_quality, deferred)
- `dream_adapter.py`, `ward_room/` — episode creation unchanged (AD-567a already handles)

---

## Test Requirements

**File: `tests/test_ad567c_anchor_quality.py`** (new)

**Anchor confidence scoring (6 tests):**
1. All 10 fields filled → confidence ≈ 1.0
2. No fields filled → confidence = 0.0
3. anchors=None → confidence = 0.0
4. Only temporal fields filled → confidence ≈ 0.25 (temporal weight)
5. Contextual dimensions (temporal+spatial+social) filled, causal+evidential empty → confidence ≈ 0.75
6. Custom dimension weights from config are respected

**RPMS confidence gating (3 tests):**
7. Episode with anchor_confidence >= gate appears in recall_weighted() results
8. Episode with anchor_confidence < gate is filtered out of recall_weighted() results
9. Filtered episode still accessible via recall_for_agent() (bypass gating)

**Per-agent anchor profiles (3 tests):**
10. Profile correctly computes mean/median confidence
11. Profile identifies weakest/strongest dimensions
12. Profile counts low-confidence episodes

**SIF check (4 tests):**
13. check_anchor_integrity passes when >50% recent episodes have anchors
14. check_anchor_integrity fails when <50% recent episodes have anchors
15. Cross-reference: episode with invalid thread_id flagged
16. SIF check handles missing episodic_memory gracefully (returns pass with "not configured")

**Drift classification (5 tests):**
17. High-confidence + out-of-domain decline → "specialization"
18. Low-confidence + any decline → "concerning"
19. No decline → "unclassified"
20. Specialization at critical severity → Counselor does NOT trigger assessment
21. Concerning at warning severity → Counselor DOES trigger assessment

**Counselor integration (2 tests):**
22. CognitiveProfile updated with anchor_quality from AnchorProfile
23. Counselor raises concern when anchor_quality < 0.3

---

## Tracking

Update PROGRESS.md, DECISIONS.md, roadmap.md on completion.

**DECISIONS.md entry:**
```
### AD-567c: Anchor Quality & Integrity
- **Date:** [completion date]
- **Status:** COMPLETE
- **Absorbs:** AD-567e (Anchor Drift Detection)
- **Decision:** Four-part anchor quality system: (1) weighted dimension confidence scoring (Johnson SMF — contextual > procedural), (2) RPMS confidence gating (suppress ungrounded memories from default recall), (3) SIF check_anchor_integrity with Video-EM cross-reference validation, (4) drift classification distinguishing healthy specialization from concerning drift using anchor confidence as discriminant.
- **Rationale:** Raw anchor completeness (AD-567b) is insufficient — dimensions have different diagnostic value per Johnson & Raye. Drift detection cannot distinguish adaptive specialization from capability loss without grounding quality signal. Echo/Meridian observation (thread 92719789) that "cognitive drift might be healthy specialization" required architectural support for classification. RPMS validates that ungrounded memories actively harm reasoning.
- **Deferred:** Guided reminiscence confabulation_rate ↔ anchor_quality correlation (future AD), cross-anchor temporal consistency checking beyond basic thread validation (future iteration).
```

---

## Deferred Items (Consolidated — remaining after AD-567c)

| Prompt | Absorbs | Scope | Depends |
|--------|---------|-------|---------|
| **AD-567d** | AD-567d + AD-462b | **Memory Lifecycle (Dream)** — anchor-preserving dream consolidation + ACT-R activation-based decay | AD-567b |
| **AD-567f** | AD-567f + AD-462d | **Social Memory** — social verification protocol + cross-agent episodic search + corroboration scoring | AD-567b |
| **AD-462c** | AD-462c + AD-462e | **Recall Depth & Oracle** — trust-gated variable recall tiers + Oracle Service cross-tier retrieval | AD-567b, AD-567c |
| **AD-567g** | standalone | **Cognitive Re-Localization** — onboarding anchor-frame establishment, O'Keefe cognitive map rebuilding | AD-567c, AD-567d |
